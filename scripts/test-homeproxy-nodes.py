"""Sequential HTTPS node checks using a native desktop sing-box 1.12.25 core.

Inputs contain credentials. Put inputs and output in a private directory. When
testing behind HomeProxy, bypass this computer's test traffic on the router first
so a failed node cannot silently use the router's existing proxy as its upstream.
"""
import argparse
import csv
from datetime import datetime, timedelta, timezone
import html
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import statistics
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request


TARGETS = ['https://www.gstatic.com/generate_204', 'https://www.cloudflare.com/cdn-cgi/trace']
STATUS = {'pending': '待测', 'passed': '主目标通过', 'alternate_only': '仅备用目标通过',
          'intermittent': '复测有失败', 'failed_this_round': '本轮未通过', 'not_exported': '未导出/不支持'}


def save_report(report, directory):
    temporary = directory / 'results.json.tmp'
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(directory / 'results.json')
    with (directory / 'results.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.writer(stream)
        writer.writerow(['节点', '协议', '结果', '延迟毫秒', '目标', '节点ID', '成功样本', '全部样本'])
        for row in report['nodes']:
            values = [row['label'], row['type'], STATUS[row['status']], row.get('delay_ms'),
                      row.get('target', ''), row['id'], row.get('successful_samples', 0),
                      row.get('sample_count', report.get('samples', 1))]
            writer.writerow(["'" + value if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else value for value in values])
    counts = {key: sum(row['status'] == key for row in report['nodes']) for key in STATUS}
    rows = []
    for row in sorted(report['nodes'], key=lambda r: (r.get('delay_ms') is None, r.get('delay_ms') or 0)):
        values = [row['label'], row['type'], STATUS[row['status']],
                  str(row['delay_ms']) if row.get('delay_ms') is not None else '—',
                  'gstatic' if row.get('target') == TARGETS[0] else ('Cloudflare' if row.get('target') else '—'),
                  str(row.get('successful_samples', 0)) + '/' + str(row.get('sample_count', report.get('samples', 1)))]
        cells = ''.join('<td>' + html.escape(value) + '</td>' for value in values)
        rows.append('<tr data-status="' + row['status'] + '" data-delay="' +
                    str(row.get('delay_ms') if row.get('delay_ms') is not None else 10**9) + '">' + cells + '</tr>')
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>节点连通性与延迟</title>
<style>body{font:16px/1.6 system-ui,sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;color:#17212b}
h1{font-size:28px;margin-bottom:8px}p{color:#485769}input,select{font:inherit;padding:8px;border:1px solid #bbc8d4;border-radius:6px;margin:8px 8px 16px 0}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:10px 12px;border-bottom:1px solid #dce3ea}th{background:#eef3f8;cursor:pointer}
tr[data-status="passed"] td:nth-child(3){color:#087345}tr[data-status="alternate_only"] td:nth-child(3),tr[data-status="intermittent"] td:nth-child(3){color:#946200}tr[data-status="failed_this_round"] td:nth-child(3){color:#b02c2c}
.summary{padding:16px;background:#eef3f8;border-radius:8px}small{color:#64748b}</style>
<h1>节点连通性与延迟</h1><p>TEST_TIME · STATE</p><div class="summary">COUNTS</div>
<p>从电脑经当前家庭宽带逐个探测，使用 sing-box 1.12.25 的 HTTPS URLTest。延迟不是 ICMP Ping 或带宽；本轮未通过不代表永久失效，备用目标结果需单独比较。多次复测取成功样本的中位数，失败单独标记。</p>
<input id="search" placeholder="筛选节点名称或协议" aria-label="筛选节点"><select id="status" aria-label="筛选结果"><option value="">全部结果</option><option value="passed">主目标通过</option><option value="alternate_only">仅备用目标通过</option><option value="intermittent">复测有失败</option><option value="failed_this_round">本轮未通过</option><option value="pending">待测</option></select>
<table><thead><tr><th>节点</th><th>协议</th><th>结果</th><th id="delay">延迟 / ms ↕</th><th>目标</th><th>成功样本</th></tr></thead><tbody>ROWS</tbody></table>
<p><small>测试不会切换家庭主节点。HTTPS 探测成功表示本次取得了 HTTPS 响应，不验证特定 HTTP 状态码、流媒体解锁、持续带宽或路由器负载能力。</small></p>
<script>const body=document.querySelector('tbody');function filter(){const q=document.querySelector('#search').value.toLowerCase(),s=document.querySelector('#status').value;for(const r of body.rows)r.hidden=!r.textContent.toLowerCase().includes(q)||(s&&r.dataset.status!==s);}document.querySelector('#search').oninput=filter;document.querySelector('#status').onchange=filter;let asc=true;document.querySelector('#delay').onclick=()=>{[...body.rows].sort((a,b)=>(Number(a.dataset.delay)-Number(b.dataset.delay))*(asc?1:-1)).forEach(r=>body.appendChild(r));asc=!asc;};</script></html>'''
    timestamp = report['tested_at'] + (' · 复测 ' + report['retested_at'] if report.get('retested_at') else '')
    state = {'complete': '检测完成', 'running': '检测中', 'interrupted': '检测已中断'}.get(report['state'], report['state'])
    page = page.replace('TEST_TIME', html.escape(timestamp)).replace('STATE', html.escape(state))
    summary = ' · '.join(f'{STATUS[key]} {value}' for key, value in counts.items() if value)
    page = page.replace('COUNTS', html.escape(summary)).replace('ROWS', ''.join(rows))
    (directory / 'results.html').write_text(page, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core', required=True, type=Path)
    parser.add_argument('--nodes', required=True, type=Path)
    parser.add_argument('--labels', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--source-ip', type=ipaddress.IPv4Address)
    parser.add_argument('--only-id', action='append', default=[])
    parser.add_argument('--samples', type=int, default=1, choices=range(1, 6))
    parser.add_argument('--timeout-ms', type=int, default=5000, choices=range(1000, 10001), metavar='1000..10000')
    args = parser.parse_args()
    core = args.core.resolve()
    version = subprocess.run([str(core), 'version'], check=True, capture_output=True, text=True, timeout=15)
    if version.stdout.splitlines()[0] != 'sing-box version 1.12.25':
        raise SystemExit('This exporter/tester is pinned to sing-box 1.12.25')
    source = json.loads(args.nodes.read_text(encoding='utf-8'))
    labels = json.loads(args.labels.read_text(encoding='utf-8'))
    if args.only_id:
        selected = set(args.only_id)
        labels = [row for row in labels if row['id'] in selected]
        if {row['id'] for row in labels} != selected:
            raise SystemExit('A requested node ID is missing from the export')
    outbounds = []
    for outbound in source['outbounds']:
        if outbound.get('type') not in ('vless', 'hysteria2') or not outbound.get('tag', '').startswith('cfg-'):
            continue
        outbound = dict(outbound)
        for key in ('routing_mark', 'bind_interface', 'inet4_bind_address', 'inet6_bind_address', 'tcp_fast_open', 'tcp_multi_path'):
            outbound.pop(key, None)
        if args.source_ip:
            outbound['inet4_bind_address'] = str(args.source_ip)
        outbounds.append(outbound)
    if not outbounds:
        raise SystemExit('No supported node outbounds in the private export')
    tags = {outbound['tag'] for outbound in outbounds}
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    secret = secrets.token_hex(24)
    config = {'log': {'level': 'error'}, 'dns': {'servers': [{'tag': 'local-dns', 'address': 'local'}],
              'final': 'local-dns', 'strategy': 'ipv4_only'},
              'outbounds': [{'type': 'direct', 'tag': 'direct-out'}, *outbounds],
              'route': {'final': 'direct-out'},
              'experimental': {'clash_api': {'external_controller': f'127.0.0.1:{port}', 'secret': secret}}}
    configuration = directory / 'temporary-core-config.json'
    configuration.write_text(json.dumps(config), encoding='utf-8')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(path, timeout=2):
        request = urllib.request.Request(f'http://127.0.0.1:{port}' + path, headers={'Authorization': 'Bearer ' + secret})
        with opener.open(request, timeout=timeout) as response:
            return json.load(response)

    report = {'tested_at': datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),
              'state': 'running', 'source': 'desktop_via_home_wan', 'source_ip': str(args.source_ip) if args.source_ip else None, 'core_version': '1.12.25',
              'concurrency': 1, 'samples': args.samples, 'timeout_ms': args.timeout_ms, 'targets': TARGETS,
              'nodes': [{**row, 'status': 'pending', 'delay_ms': None, 'attempts': []} for row in labels]}
    environment = os.environ.copy()
    environment.update(GOMEMLIMIT='128MiB', GOGC='50')
    creation_flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    process = None
    try:
        with (directory / 'core-error.log').open('wb') as errors:
            process = subprocess.Popen([str(core), 'run', '--config', str(configuration)], stdout=subprocess.DEVNULL,
                                       stderr=errors, env=environment, creationflags=creation_flags)
            deadline = time.monotonic() + 15
            while True:
                if process.poll() is not None:
                    raise RuntimeError('Desktop test core failed to start; inspect the private core-error.log')
                try:
                    call('/version')
                    break
                except (OSError, ValueError):
                    if time.monotonic() > deadline:
                        raise RuntimeError('Desktop test API did not become ready')
                    time.sleep(0.2)
            save_report(report, directory)
            for index, row in enumerate(report['nodes'], 1):
                tag = 'cfg-' + row['id'] + '-out'
                if tag not in tags:
                    row['status'] = 'not_exported'
                else:
                    for target in TARGETS:
                        query = urllib.parse.urlencode({'timeout': args.timeout_ms, 'url': target})
                        path = '/proxies/' + urllib.parse.quote(tag, safe='') + '/delay?' + query
                        try:
                            result = call(path, timeout=args.timeout_ms / 1000 + 3)
                            delay = result.get('delay')
                            if not isinstance(delay, int) or isinstance(delay, bool) or delay < 0:
                                raise ValueError('No valid delay')
                            row['attempts'].append({'target': target, 'delay_ms': delay})
                            row.update(status='passed' if target == TARGETS[0] else 'alternate_only', delay_ms=delay, target=target)
                            samples = [delay]
                            for _ in range(args.samples - 1):
                                try:
                                    result = call(path, timeout=args.timeout_ms / 1000 + 3)
                                    sample = result.get('delay')
                                    if not isinstance(sample, int) or isinstance(sample, bool) or sample < 0:
                                        raise ValueError('No valid delay')
                                    samples.append(sample)
                                    row['attempts'].append({'target': target, 'delay_ms': sample})
                                except (OSError, ValueError):
                                    row['attempts'].append({'target': target, 'delay_ms': None, 'error': 'repeat_failed'})
                                    row['status'] = 'intermittent'
                            row['successful_samples'] = len(samples)
                            row['delay_ms'] = round(statistics.median(samples))
                            break
                        except (OSError, ValueError) as error:
                            row['attempts'].append({'target': target, 'delay_ms': None,
                                                    'error': 'http_' + str(error.code) if isinstance(error, urllib.error.HTTPError) else type(error).__name__})
                    if row['status'] == 'pending':
                        row['status'] = 'failed_this_round'
                save_report(report, directory)
                print(json.dumps({'completed': index, 'total': len(labels), 'label': row['label'],
                                  'status': row['status'], 'delay_ms': row['delay_ms']}), flush=True)
                time.sleep(0.25)
            report['state'] = 'complete'
            save_report(report, directory)
    except BaseException:
        report['state'] = 'interrupted'
        save_report(report, directory)
        raise
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        configuration.unlink(missing_ok=True)
    print(json.dumps({'report': str(directory / 'results.html'), 'state': report['state']}), flush=True)


if __name__ == '__main__':
    main()
