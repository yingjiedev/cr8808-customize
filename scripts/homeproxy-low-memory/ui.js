// CR8808: one manual probe or one browser-driven serial queue, never background scans.
const cr8808TestStart = rpc.declare({object: 'luci.homeproxy', method: 'node_test_start', params: ['node']});
const cr8808TestStatus = rpc.declare({object: 'luci.homeproxy', method: 'node_test_status', params: ['id']});
let cr8808Testing = false;
let cr8808Queue = null;
let cr8808Controls = null;
const cr8808Errors = {
	apply_first: '请先保存并应用；当前支持 VLESS / Hysteria2，最多登记 64 个节点。',
	low_memory: '可用内存不足 10 MiB，队列已停止，请稍后重试。',
	busy: '已有其他检测任务，队列已停止，请等待该任务结束。',
	start_failed: '检测未启动，请稍后重试。',
	expired: '检测状态已过期，请稍后重试。'
};
function cr8808ProbeError(code) {
	const error = new Error(cr8808Errors[code] || '检测通信异常，队列已停止。');
	error.code = code;
	return error;
}
function cr8808Wait(milliseconds) {
	return new Promise(function(resolve) { window.setTimeout(resolve, milliseconds); });
}
async function cr8808Probe(button, sectionId) {
	const original = button.textContent;
	button.disabled = true;
	button.textContent = '检测中…';
	try {
		const job = await cr8808TestStart(sectionId);
		if (!job.id)
			throw cr8808ProbeError(job.error);
		const deadline = Date.now() + 17000;
		await cr8808Wait(700);
		while (true) {
			const result = await cr8808TestStatus(job.id);
			if (result.status === 'running' && Date.now() < deadline) {
				await cr8808Wait(1000);
				continue;
			}
			if (result.status === 'running' || result.error === 'expired' || result.error === 'invalid_job')
				throw cr8808ProbeError('expired');
			if (!['success', 'failed'].includes(result.status))
				throw cr8808ProbeError('rpc_error');
			button.textContent = result.status === 'success' ? result.delay + ' ms · 重测' : '本次未通过 · 重测';
			button.title = '经此路由器和所选节点访问 gstatic 的 HTTPS 延迟；点击重测。失败不代表节点永久不可用。';
			return result;
		}
	} catch (error) {
		button.textContent = error.code === 'apply_first' ? '需先保存应用' : original;
		throw error;
	} finally {
		button.disabled = false;
	}
}
function cr8808SetTesting(active) {
	cr8808Testing = active;
	if (cr8808Controls)
		cr8808Controls.start.disabled = active;
}
async function cr8808TestNode(ev, sectionId) {
	if (cr8808Testing) {
		ui.addNotification(null, E('p', '已有节点正在检测，请等待完成或停止排队。'));
		return;
	}
	cr8808SetTesting(true);
	try {
		return await cr8808Probe(ev.currentTarget, sectionId);
	} catch (error) {
		ui.addNotification(null, E('p', error.message || String(error)));
	} finally {
		cr8808SetTesting(false);
	}
}
function cr8808CollectNodes(root) {
	const seen = new Set();
	return Array.from(root.querySelectorAll('[data-field$="._cr8808_latency"]')).reduce(function(entries, field) {
		const id = (field.getAttribute('data-field') || '').split('.')[2];
		const button = field.querySelector('button');
		if (!id || !button || seen.has(id) || !['vless', 'hysteria2'].includes(uci.get('homeproxy', id, 'type')))
			return entries;
		seen.add(id);
		entries.push({ id: id, label: uci.get('homeproxy', id, 'label') || id, button: button });
		return entries;
	}, []);
}
function cr8808StopQueue() {
	if (cr8808Queue) {
		cr8808Queue.cancelled = true;
		cr8808Queue.controls.stop.disabled = true;
		cr8808Queue.controls.status.textContent = '正在停止排队；当前节点测完后停止。';
	}
}
function cr8808QueueProgress(queue, label) {
	return label + ' ' + queue.done + '/' + queue.total +
		' · 通过 ' + queue.success + ' · 本次未通过 ' + queue.failed + ' · 跳过 ' + queue.skipped;
}
async function cr8808RunQueue(entries, controls, connected) {
	if (cr8808Testing) {
		ui.addNotification(null, E('p', '已有节点正在检测，请等待完成。'));
		return;
	}
	if (!entries.length) {
		controls.status.textContent = '没有可检测节点；请先保存应用 VLESS / Hysteria2 节点。';
		return;
	}
	const queue = { total: entries.length, done: 0, success: 0, failed: 0, skipped: 0, cancelled: false, controls: controls };
	cr8808Queue = queue;
	cr8808SetTesting(true);
	controls.start.disabled = true;
	controls.stop.disabled = false;
	let reason = '';
	try {
		for (const entry of entries) {
			if (queue.cancelled || !connected()) {
				queue.cancelled = true;
				break;
			}
			controls.status.textContent = cr8808QueueProgress(queue, '检测中') + ' · 当前：' + entry.label;
			try {
				const result = await cr8808Probe(entry.button, entry.id);
				queue[result.status === 'success' ? 'success' : 'failed']++;
			} catch (error) {
				if (error.code !== 'apply_first') {
					reason = error.message || String(error);
					break;
				}
				queue.skipped++;
			}
			queue.done++;
			controls.status.textContent = cr8808QueueProgress(queue, '检测中');
			if (queue.cancelled || queue.done === queue.total)
				break;
			// Leave scheduling and network headroom for household traffic.
			await cr8808Wait(1000);
		}
	} finally {
		const label = reason ? '已中止' : queue.cancelled ? '已停止' : '已完成';
		controls.status.textContent = cr8808QueueProgress(queue, label) +
			(queue.done < queue.total ? ' · 未测 ' + (queue.total - queue.done) : '') + (reason ? ' · ' + reason : '');
		controls.stop.disabled = true;
		controls.start.disabled = false;
		cr8808Queue = null;
		cr8808SetTesting(false);
	}
	return queue;
}
function cr8808NodeTools(root) {
	const controls = {
		start: E('button', { type: 'button', class: 'cbi-button cbi-button-action' }, '全部测试（逐个排队）'),
		stop: E('button', { type: 'button', class: 'cbi-button', disabled: true }, '停止排队'),
		status: E('span', { role: 'status', 'aria-live': 'polite' }, '尚未开始')
	};
	cr8808Controls = controls;
	controls.start.addEventListener('click', function() {
		return cr8808RunQueue(cr8808CollectNodes(root), controls, function() { return root.isConnected; }).catch(function(error) {
			ui.addNotification(null, E('p', error.message || String(error)));
		});
	});
	controls.stop.addEventListener('click', cr8808StopQueue);
	window.addEventListener('pagehide', cr8808StopQueue, { once: true });
	const toolbar = E('div', { class: 'cbi-section', style: 'padding:12px;margin:12px 0' }, [
		E('div', { style: 'display:flex;flex-wrap:wrap;gap:8px;align-items:center' }, [controls.start, controls.stop, controls.status]),
		E('p', { style: 'margin:8px 0 0' }, '每次 1 个，间隔 1 秒；覆盖各订阅标签中的可测节点。请保留此页面，刷新或离开会停止后续排队；打开页面不会自动测速。')
	]);
	const description = root.querySelector('.cbi-map-descr') || root.querySelector('h2');
	if (description && description.parentNode === root)
		root.insertBefore(toolbar, description.nextSibling);
	else
		root.insertBefore(toolbar, root.firstChild);
	return root;
}
