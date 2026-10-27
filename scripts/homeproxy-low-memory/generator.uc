// CR8808: reuse this core for explicitly requested, serial node tests.
// Unselected outbounds do not join URLTest or receive scheduled probes.
const test_secret = trim(readfile(HP_DIR + '/node-test.secret') || '');
if (length(test_secret) !== 64 || !match(test_secret, /^[a-f0-9]+$/))
	die('Missing private node-test controller secret.');
let test_index = {};
if (routing_mode !== 'custom') {
	let test_tags = map(config.outbounds, (outbound) => outbound.tag);
	uci.foreach(uciconfig, ucinode, (node) => {
		if (!(node.type in ['vless', 'hysteria2']) || length(keys(test_index)) >= 64)
			return;
		const id = node['.name'];
		if (!match(id, /^[a-zA-Z0-9_]{1,64}$/) || !node.address || !node.port ||
		    (node.type === 'vless' && !node.uuid) ||
		    (node.type === 'hysteria2' && !node.password))
			return;
		let tag = 'cfg-' + id + '-out';
		if (id === main_node)
			tag = 'main-out';
		else if (dedicated_udp_node && id === main_udp_node)
			tag = 'main-udp-out';
		if (index(test_tags, tag) < 0) {
			push(config.outbounds, generate_outbound(node));
			push(test_tags, tag);
		}
		test_index[id] = {
			tag,
			fingerprint: md5(join('\n', map(sort(filter(keys(node), (key) => substr(key, 0, 1) !== '.')), (key) => key + '=' + sprintf('%J', node[key]))))
		};
	});
}
if (!config.experimental)
	config.experimental = {};
config.experimental.clash_api = {
	external_controller: '127.0.0.1:9091',
	secret: test_secret,
	access_control_allow_origin: ['http://localhost'],
	access_control_allow_private_network: false
};
// DNS caching stays enabled; bound it for this small router.
config.dns.cache_capacity = 256;
writefile(RUN_DIR + '/node-test-index.json', sprintf('%J', test_index));
chmod(RUN_DIR + '/node-test-index.json', 384);
