"""Offline structural checks; external schema tool is optional."""
from pathlib import Path
import re
import shutil
import subprocess
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / 'deploy/k8s/deployment.yaml'
SECRETS = {'TELEGRAM_TOKEN', 'GIGACHAT_KEY', 'YANDEX_API_KEY', 'YANDEX_FOLDER_ID',
           'ADMIN_IDS', 'TICKETING_WEBHOOK_URL', 'HR_CHAT_ID'}


def test_deployment_service_and_overlay():
    text = MANIFEST.read_text()
    docs = {doc['kind']: doc for doc in yaml.safe_load_all(text)}
    assert set(docs) == {'Deployment', 'Service', 'ConfigMap'}
    deploy = docs['Deployment']
    assert deploy['apiVersion'] == 'apps/v1'
    assert deploy['spec']['replicas'] == 1
    pod = deploy['spec']['template']['spec']
    assert pod['securityContext']['runAsNonRoot'] is True
    assert pod['securityContext']['runAsUser'] == 1000
    assert pod['securityContext']['fsGroup'] == 1000
    app = pod['containers'][0]
    assert app['resources'] == {'requests': {'cpu': '1', 'memory': '2Gi'},
                                'limits': {'cpu': '2', 'memory': '4Gi'}}
    for container in [app, *pod['initContainers']]:
        security = container['securityContext']
        assert security['readOnlyRootFilesystem'] is True
        assert security['allowPrivilegeEscalation'] is False
        assert security['capabilities']['drop'] == ['ALL']
    for probe in ('readinessProbe', 'livenessProbe'):
        assert app[probe]['httpGet'] == {'path': '/health', 'port': 8080}
        assert app[probe]['initialDelaySeconds'] == 15
        assert app[probe]['periodSeconds'] == 10
        assert app[probe]['timeoutSeconds'] == 3
        assert app[probe]['failureThreshold'] == 3
    env = {entry['name']: entry for entry in app['env']}
    assert set(env) == SECRETS | {'ANALYTICS_PATH'}
    for name in SECRETS:
        assert env[name] == {'name': name, 'valueFrom': {
            'secretKeyRef': {'name': 'telegram-secrets', 'key': name}}}
    assert env['ANALYTICS_PATH']['value'] == '/data/analytics/unanswered.jsonl'
    mounts = {entry['name']: entry for entry in app['volumeMounts']}
    assert mounts['config-overlay'] == {'name': 'config-overlay',
        'mountPath': '/app/config/config.yaml', 'subPath': 'config/config.yaml', 'readOnly': True}
    assert mounts['analytics-data']['mountPath'] == '/data'
    volumes = {volume['name']: volume for volume in pod['volumes']}
    assert volumes['analytics-data']['emptyDir'] == {}
    assert volumes['config-overlay']['configMap']['name'] == docs['ConfigMap']['metadata']['name']
    overlay = yaml.safe_load(docs['ConfigMap']['data']['config.yaml'])
    source = yaml.safe_load((ROOT / 'config/config.yaml').read_text())
    for key, value in source.items():
        assert overlay[key] == value
    assert overlay['http_server'] == {'enabled': True, 'port': 8080}
    assert overlay['analytics']['unanswered_path'] == '/data/analytics/unanswered.jsonl'
    assert overlay['vectorstore']['faiss']['indices_dir'] == '/data/faiss'
    assert docs['Service']['spec']['type'] == 'ClusterIP'
    assert docs['Service']['spec']['ports'][0]['port'] == 8080
    assert docs['Service']['spec']['ports'][0]['targetPort'] == 8080
    assert not re.search(r'eyJ|sk-|password=', text)


def test_kubeconform_offline():
    executable = shutil.which('kubeconform')
    if not executable:
        pytest.skip('kubeconform not installed; schema validated offline by structure assertions above')
    schemas = ROOT / '.agent/artifacts/infra_checks/kubernetes-json-schema'
    if not schemas.is_dir():
        pytest.skip('kubeconform installed but local offline JSON schemas absent; network validation prohibited')
    result = subprocess.run([executable, '-strict', '-summary', '-schema-location',
        str(schemas / '{{.ResourceKind}}.json'), str(MANIFEST)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
