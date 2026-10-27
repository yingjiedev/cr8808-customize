// CR8808: a manual probe, with a page-wide serial gate and bounded polling.
const cr8808TestStart = rpc.declare({object: 'luci.homeproxy', method: 'node_test_start', params: ['node']});
const cr8808TestStatus = rpc.declare({object: 'luci.homeproxy', method: 'node_test_status', params: ['id']});
let cr8808Testing = false;
function cr8808TestNode(ev, sectionId) {
	if (cr8808Testing) {
		ui.addNotification(null, E('p', '已有节点正在检测，请等待完成。'));
		return Promise.resolve();
	}
	const button = ev.currentTarget;
	const original = button.textContent;
	const errors = {
		apply_first: '请先保存并应用；当前支持 VLESS / Hysteria2，最多 64 个节点。',
		low_memory: '可用内存不足 10 MiB，请稍后重试。',
		busy: '已有节点正在检测，请等待完成。',
		start_failed: '检测未启动，请稍后重试。'
	};
	cr8808Testing = true;
	button.disabled = true;
	button.textContent = '检测中…';
	let timer;
	const deadline = Date.now() + 17000;
	return cr8808TestStart(sectionId).then(function(job) {
		if (!job.id)
			throw new Error(errors[job.error] || '无法开始检测。');
		return new Promise(function(resolve, reject) {
			function pollResult() {
				cr8808TestStatus(job.id).then(function(result) {
					if (result.status === 'running' && Date.now() < deadline) {
						timer = window.setTimeout(pollResult, 1000);
						return;
					}
					button.textContent = result.status === 'success' ? result.delay + ' ms · 重测' : '本次未通过 · 重测';
					button.title = '经此路由器和所选节点访问 gstatic 的 HTTPS 延迟；点击重测。失败不代表节点永久不可用。';
					resolve();
				}).catch(reject);
			}
			timer = window.setTimeout(pollResult, 700);
		});
	}).catch(function(error) {
		button.textContent = original;
		ui.addNotification(null, E('p', error.message || String(error)));
	}).finally(function() {
		window.clearTimeout(timer);
		button.disabled = false;
		cr8808Testing = false;
	});
}
