// Applied on the candidate only. --check validates without committing anything.
import { cursor } from 'uci';
import { readfile, writefile, unlink } from 'fs';

const dry_run = ARGV[0] === '--check';
const identity_only = ARGV[0] === '--identity-only';
const config_dir = ARGV[1] || '/etc/config';
const data_path = ARGV[2] || '/etc/cr8808-nss/private-settings.json';
const data = json(readfile(data_path));
if (data.schema_version !== 1)
	die('Unsupported private migration schema\n');
function require(ok, message) {
	if (!ok) die(message + '\n');
}
function preserve_root() {
	require(trim(readfile('/tmp/sysinfo/board_name') || '') === 'xiaomi,cr8806', 'Apply mode requires the candidate board');
	let shadow = readfile('/etc/shadow');
	require(shadow, 'Candidate shadow file missing');
	let lines = split(shadow, '\n'), found = false;
	for (let i = 0; i < length(lines); i++) {
		if (substr(lines[i], 0, 5) === 'root:') {
			lines[i] = data.root_shadow;
			found = true;
		}
	}
	require(found, 'Candidate root identity missing');
	require(writefile('/etc/shadow', join('\n', lines)) !== null, 'Unable to preserve root password hash');
}
if (identity_only) {
	preserve_root();
	exit(0);
}
const ctx = cursor(config_dir, '/tmp/.uci-cr8808-migration', '');
function options(config, section, values) {
	for (let key, value in values)
		require(ctx.set(config, section, key, value), 'Unable to map a private setting');
}

// Discover the new radios by band. Never copy old path/device names.
let devices = {}, ifaces = {};
ctx.foreach('wireless', 'wifi-device', function(s) {
	require(s.band === '2g' || s.band === '5g', 'Unexpected candidate radio band');
	require(!devices[s.band], 'Duplicate candidate radio band');
	devices[s.band] = s['.name'];
});
ctx.foreach('wireless', 'wifi-iface', function(s) {
	if (s.mode !== 'ap') return;
	if (!ifaces[s.device]) ifaces[s.device] = [];
	push(ifaces[s.device], s['.name']);
});
for (let old in data.radios) {
	let device = devices[old.band];
	require(device, 'Missing candidate radio for a required band');
	require(length(ifaces[device]) === 1, 'Inspect the candidate AP layout before migration');
	let hardware_path = ctx.get('wireless', device, 'path');
	options('wireless', device, old.device_options);
	options('wireless', ifaces[device][0], old.ap_options);
	require(ctx.get('wireless', device, 'path') === hardware_path, 'Candidate hardware path changed');
	for (let key in ['ssid', 'encryption', 'key'])
		require(ctx.get('wireless', ifaces[device][0], key) === old.ap_options[key], 'Wireless mapping verification failed');
}

const lan_device = ctx.get('network', 'lan', 'device');
const wan_device = ctx.get('network', 'wan', 'device');
for (let name, values in data.network)
	options('network', name, values);
require(ctx.get('network', 'lan', 'device') === lan_device, 'Candidate LAN device changed');
require(ctx.get('network', 'wan', 'device') === wan_device, 'Candidate WAN device changed');
if (data.globals && length(data.globals)) {
	let globals = ctx.get_first('network', 'globals');
	require(globals, 'Candidate network globals missing');
	options('network', globals, data.globals);
}
let system = ctx.get_first('system', 'system');
require(system, 'Candidate system section missing');
options('system', system, data.system);
ctx.foreach('dhcp', 'dhcp', function(s) {
	if (s.interface === 'lan' && s.ignore !== '1')
		require(ctx.set('dhcp', s['.name'], 'dhcpv4', 'server'), 'Cannot enable LAN DHCPv4');
});
// Keep the initial wired NSS check separate from proxy startup. Credentials and
// nodes are preserved, and proxy startup can be enabled after the first checks.
require(ctx.set('homeproxy', 'config', 'cr8808_autostart', '0'), 'HomeProxy config missing');
if (dry_run) {
	print('Private migration mapping validated without commits.\n');
	exit(0);
}
require(config_dir === '/etc/config', 'Apply mode requires the real candidate configuration directory');
preserve_root();
for (let name in ['network', 'wireless', 'dhcp', 'system', 'homeproxy'])
	require(ctx.commit(name), 'Unable to commit private settings');
require(unlink(data_path), 'Unable to remove temporary private settings');
print('Private migration applied; proxy autostart is disabled for initial wired checks.\n');
