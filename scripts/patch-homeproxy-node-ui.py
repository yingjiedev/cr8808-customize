"""Build the pinned HomeProxy generator/RPC/node-page patch, without installing it."""
import argparse
import hashlib
from pathlib import Path

ASSETS = Path(__file__).parent / 'homeproxy-low-memory'
GENERATOR_SHA = '7545f12f2af648ab09c64bea943257ed5c768f8689d910d3beb9aed15b069812'
RPC_SHA = 'e448c9da33f913f3f1068916db95e24b5e1d3024830b96d7929a7be6356917fe'
NODE_SHA = '88e7e4bb10f1d44e184ff3f6ebb96851ccf5c6a6aed5a50ee4600e415e312872'


def checked(path, expected):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f'Unexpected installed HomeProxy source: {path.name}')
    return data.decode('utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generator', required=True, type=Path)
    parser.add_argument('--rpc', required=True, type=Path)
    parser.add_argument('--node-js', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        gen = checked(args.generator, GENERATOR_SHA)
        rpc_source = checked(args.rpc, RPC_SHA)
        node = checked(args.node_js, NODE_SHA)
        gen = gen.replace("import { readfile, writefile } from 'fs';", "import { chmod, readfile, writefile } from 'fs';\nimport { md5 } from 'digest';", 1)
        anchor = "writefile(RUN_DIR + '/sing-box-c.json', sprintf('%.J\\n', removeBlankAttrs(config)));"
        if gen.count(anchor) != 1:
            raise ValueError('Unexpected generator write anchor')
        gen = gen.replace(anchor, (ASSETS / 'generator.uc').read_text(encoding='utf-8') + '\n' + anchor + "\nsystem('chgrp sing-box ' + RUN_DIR + '/sing-box-c.json && chmod 640 ' + RUN_DIR + '/sing-box-c.json');")
        rpc_source = rpc_source.replace("import { access, error, lstat, popen, readfile, writefile } from 'fs';", "import { access, chmod, error, lstat, mkdir, popen, readfile, rmdir, unlink, writefile } from 'fs';\nimport { cursor } from 'uci';\nimport { md5 } from 'digest';", 1)
        rpc_source = rpc_source.replace('const methods = {', 'const methods = {\n' + (ASSETS / 'rpc.uc').read_text(encoding='utf-8'), 1)
        node = node.replace("'require form';", "'require form';'require rpc';", 1)
        anchor = 'function allowInsecureConfirm('
        if node.count(anchor) != 1:
            raise ValueError('Unexpected node view anchor')
        node = node.replace(anchor, '\n' + (ASSETS / 'ui.js').read_text(encoding='utf-8') + '\n' + anchor, 1)
        anchor = "o=s.option(form.Value,'label',_('Label'));"
        if node.count(anchor) != 1:
            raise ValueError('Unexpected node row anchor')
        button = "o=s.option(form.Button,'_cr8808_latency','HTTPS 延迟');o.editable=true;o.modalonly=false;o.inputtitle='测试延迟';o.inputstyle='action';o.onclick=cr8808TestNode;"
        node = node.replace(anchor, button + anchor, 1)
        node = node.replace("m=new form.Map('homeproxy',_('Edit nodes'));", "m=new form.Map('homeproxy',_('Edit nodes'),'点击节点的“测试延迟”逐个检测，HTTPS 探测 5 秒超时，首轮可能更久。请先保存应用节点变更。');", 1)
        if node.count('return m.render();') != 1:
            raise ValueError('Unexpected node map render anchor')
        node = node.replace('return m.render();', 'return m.render().then(cr8808NodeTools);', 1)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    args.output.mkdir(parents=True, exist_ok=False)
    for name, content in [('generate_client.uc', gen), ('luci.homeproxy', rpc_source), ('node.js', node), ('cr8808-node-test-worker.uc', (ASSETS / 'worker.uc').read_text(encoding='utf-8'))]:
        data = content.encode('utf-8')
        (args.output / name).write_bytes(data)
        print(f'{name}: {len(data)} bytes, sha256={hashlib.sha256(data).hexdigest()}')


if __name__ == '__main__':
    main()
