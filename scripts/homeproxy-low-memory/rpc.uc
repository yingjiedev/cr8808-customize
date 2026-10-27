// CR8808: on-demand tests; no probe, process, or polling on page open.
node_test_start: {
	args: { node: 'node' },
	call: function(req) {
		const id = req.args?.node;
		if (type(id) !== 'string' || !match(id, /^[a-zA-Z0-9_]{1,64}$/))
			return { error: 'invalid_node' };
		let index_data;
		try { index_data = json(readfile(RUN_DIR + '/node-test-index.json') || '{}'); }
		catch (e) { return { error: 'apply_first' }; }
		if (!index_data[id])
			return { error: 'apply_first' };
		const uc = cursor();
		const node = uc.get_all('homeproxy', id);
		if (!node || md5(join('\n', map(sort(filter(keys(node), (key) => substr(key, 0, 1) !== '.')), (key) => key + '=' + sprintf('%J', node[key])))) !== index_data[id].fingerprint)
			return { error: 'apply_first' };
		const mem = match(readfile('/proc/meminfo') || '', /MemAvailable:\s+(\d+)/);
		if (!mem || +mem[1] < 10240)
			return { error: 'low_memory' };
		const lock = RUN_DIR + '/node-test.lock';
		let previous;
		try { previous = json(readfile(lock + '/job.json') || '{}'); } catch (e) { previous = {}; }
		if (lstat(lock)) {
			if (!previous.started || time() - previous.started < 20)
				return { error: 'busy' };
			unlink(lock + '/job.json');
			unlink(lock + '/request.http');
			unlink(lock + '/response.http');
			rmdir(lock);
		}
		if (!mkdir(lock, 448))
			return { error: 'busy' };
		const job = { id: md5(id + ':' + time() + ':' + readfile('/proc/sys/kernel/random/uuid')), node: id, tag: index_data[id].tag, started: time(), status: 'running' };
		if (!writefile(lock + '/job.json', sprintf('%J', job))) {
			rmdir(lock);
			return { error: 'start_failed' };
		}
		chmod(lock + '/job.json', 384);
		const rc = system('/usr/bin/ucode /etc/homeproxy/scripts/cr8808-node-test-worker.uc </dev/null >/dev/null 2>&1 &');
		if (rc !== 0) {
			unlink(lock + '/job.json');
			rmdir(lock);
			return { error: 'start_failed' };
		}
		return { id: job.id, status: 'running' };
	}
},
node_test_status: {
	args: { id: 'id' },
	call: function(req) {
		const id = req.args?.id;
		if (type(id) !== 'string' || !match(id, /^[a-f0-9]{32}$/))
			return { error: 'invalid_job' };
		let result, job;
		try { result = json(readfile(RUN_DIR + '/node-test-result-' + id + '.json') || '{}'); } catch (e) {}
		if (result?.id === id)
			return result;
		try { job = json(readfile(RUN_DIR + '/node-test.lock/job.json') || '{}'); } catch (e) {}
		if (job?.id === id && time() - job.started < 15)
			return { id, status: 'running' };
		return { id, status: 'failed', error: 'expired' };
	}
},
