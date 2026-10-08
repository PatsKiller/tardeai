"""A promote/rollback must reach the n8n daemons that freeze CURRENT at startup."""
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

def test_default_rebind_restarts_gateway_relay_and_executor(tmp_path):
    source=(ROOT/'scripts/cio_phase2_exact_main_deploy.sh').read_text()
    function=re.search(r'^restart_root_frozen_units\(\) \{.*?^\}',source,re.M|re.S).group()
    fake=tmp_path/'bin'
    fake.mkdir()
    (fake/'systemctl').write_text('#!/bin/bash\nif [[ "$*" == *"restart"* ]]; then echo "${@: -1}" >> "$REBINDS"; fi\nif [[ "$*" == *"MainPID"* ]]; then echo 123; fi\nexit 0\n')
    (fake/'sleep').write_text('#!/bin/bash\nexit 0\n')
    (fake/'readlink').write_text('#!/bin/bash\necho /release/expected\n')
    for p in fake.iterdir():
        p.chmod(0o755)
    report=tmp_path/'calls'
    env={**os.environ,'PATH':str(fake)+':'+os.environ['PATH'],'REBINDS':str(report)}
    env.pop('TRADEAI_CURRENT_BOUND_UNITS',None)
    result=subprocess.run(['bash','-c','log() { :; }\n'+function+'\nrestart_root_frozen_units /release/expected'],env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert {'tradeai-n8n-coordination-gateway.service','tradeai-n8n-run-relay.service','tradeai-n8n-run-executor.service'} <= set(report.read_text().splitlines())


@pytest.mark.parametrize('defect', ['restart_failed', 'stale_cwd'])
def test_failed_or_stale_rebind_cannot_be_reported_as_success(tmp_path, defect):
    source=(ROOT/'scripts/cio_phase2_exact_main_deploy.sh').read_text()
    function=re.search(r'^restart_root_frozen_units\(\) \{.*?^\}',source,re.M|re.S).group()
    fake=tmp_path/'bin'; fake.mkdir()
    (fake/'systemctl').write_text('#!/bin/bash\nif [[ "$*" == *"restart"* && "$DEFECT" == restart_failed ]]; then exit 1; fi\nif [[ "$*" == *"MainPID"* ]]; then echo 123; fi\nexit 0\n')
    (fake/'sleep').write_text('#!/bin/bash\nexit 0\n')
    (fake/'readlink').write_text('#!/bin/bash\necho /release/old\n')
    for p in fake.iterdir():p.chmod(0o755)
    env={**os.environ,'PATH':str(fake)+':'+os.environ['PATH'],'DEFECT':defect,
         'TRADEAI_CURRENT_BOUND_UNITS':'tradeai-n8n-run-executor.service'}
    run=subprocess.run(['bash','-c','log() { :; }\n'+function+'\nrestart_root_frozen_units /release/expected'],env=env,capture_output=True,text=True)
    assert run.returncode!=0
