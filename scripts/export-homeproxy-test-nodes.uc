#!/usr/bin/ucode
/* Use the installed generator for a private export without changing the service. */
'use strict';

import { chmod, lstat, mkdir, readfile, writefile } from 'fs';
import { cursor } from 'uci';

const directory = '/tmp/cr8808-node-export';
const existing = lstat(directory);
if (existing && (existing.type !== 'directory' || existing.uid !== 0))
	die('Refusing to use an export path not owned by root.');
if (!existing && !mkdir(directory, 448))
	die('Could not create the private export directory.');
chmod(directory, 448);
const config_path = directory + '/nodes.json';
const labels_path = directory + '/labels.json';
for (let path in [config_path, labels_path]) {
	const file = lstat(path);
	if (file && (file.type !== 'file' || file.uid !== 0))
		die('Refusing to overwrite an unexpected export file.');
}
let source = readfile('/etc/homeproxy/scripts/generate_client.uc');
const anchor = "writefile(RUN_DIR + '/sing-box-c.json', sprintf('%.J\\n', removeBlankAttrs(config)));";
if (!source || length(split(source, anchor)) !== 2 ||
    index(source, 'function generate_outbound(node)') < 0)
	die('Unexpected HomeProxy generator; export stopped before execution.');

const extra = `
// Export-only dormant outbounds: no change to the running main selector.
const export_tags = map(config.outbounds, (outbound) => outbound.tag);
uci.foreach(uciconfig, ucinode, (node) => {
	if (!(node.type in ['vless', 'hysteria2']))
		return;
	const tag = 'cfg-' + node['.name'] + '-out';
	if (~index(export_tags, tag))
		return;
	push(config.outbounds, generate_outbound(node));
	push(export_tags, tag);
});
writefile('${config_path}', sprintf('%.J\\n', removeBlankAttrs(config)));
`;
source = replace(source, anchor, extra);
loadstring(source)();
chmod(config_path, 384);

const uci = cursor();
let nodes = [];
uci.foreach('homeproxy', 'node', (node) => {
	push(nodes, { id: node['.name'], label: node.label || node['.name'], type: node.type });
});
writefile(labels_path, sprintf('%.J\n', nodes));
chmod(labels_path, 384);
print(sprintf('Exported %d node labels; credentials stay in the private JSON export.\n', length(nodes)));
