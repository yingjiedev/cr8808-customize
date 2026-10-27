#!/usr/bin/ucode
// One short-lived ucode worker + minimal BusyBox nc; never another sing-box.
'use strict';
import { chmod, glob, lstat, readfile, rename, rmdir, unlink, writefile } from 'fs';
const directory = '/var/run/homeproxy';
const lock = directory + '/node-test.lock';
let job;
try { job = json(readfile(lock + '/job.json') || '{}'); } catch (e) { exit(1); }
if (!job?.id || !match(job.id, /^[a-f0-9]{32}$/) ||
    !match(job.tag || '', /^(main(-udp)?-out|cfg-[a-zA-Z0-9_]{1,64}-out)$/))
	exit(1);
const result = { id: job.id, node: job.node, status: 'failed', target: 'gstatic', finished: time() };
const request_file = lock + '/request.http';
const response_file = lock + '/response.http';
try {
	const secret = trim(readfile('/etc/homeproxy/node-test.secret') || '');
	if (!match(secret, /^[a-f0-9]{64}$/))
		die('Missing controller secret');
	const path = '/proxies/' + job.tag + '/delay?timeout=5000&url=https%3A%2F%2Fwww.gstatic.com%2Fgenerate_204';
	writefile(request_file, 'GET ' + path + ' HTTP/1.0\r\nHost: 127.0.0.1:9091\r\nAuthorization: Bearer ' + secret + '\r\nConnection: close\r\n\r\n');
	chmod(request_file, 384);
	// system's native millisecond deadline kills this sole exec'ed nc process.
	// This firmware's minimal nc has no -w, and no timeout applet is installed.
	const command = 'umask 077; exec /bin/busybox nc 127.0.0.1 9091 < ' + request_file + ' > ' + response_file + ' 2>/dev/null';
	if (system(command, 10000) !== 0)
		die('Local request deadline or connection error');
	const http = readfile(response_file) || '';
	if (length(http) > 8192 || !match(http, /^HTTP\/1\.[01] 200 /) || index(http, '\r\n\r\n') < 0)
		die('Local request did not return success');
	const response = json(substr(http, index(http, '\r\n\r\n') + 4));
	if (type(response?.delay) === 'int' && response.delay > 0 && response.delay <= 65535) {
		result.status = 'success';
		result.delay = response.delay;
	}
} catch (e) {
	// Do not expose upstream addresses, authentication, or raw core errors.
	result.error = 'probe_failed';
}
result.finished = time();
// Ignore a worker from an expired job rather than overwrite a newer result.
let current;
try { current = json(readfile(lock + '/job.json') || '{}'); } catch (e) {}
if (current?.id === job.id) {
	unlink(request_file);
	unlink(response_file);
	let cached = glob(directory + '/node-test-result-*.json') || [];
	sort(cached, (a, b) => lstat(a).mtime - lstat(b).mtime);
	while (length(cached) >= 8)
		unlink(shift(cached));
	const temporary = directory + '/node-test-result.tmp';
	writefile(temporary, sprintf('%J', result));
	chmod(temporary, 384);
	rename(temporary, directory + '/node-test-result-' + job.id + '.json');
	unlink(lock + '/job.json');
	rmdir(lock);
}
