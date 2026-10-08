"""Stop exactly the enclave launched by this service, never --all."""
import json
import re
import subprocess
import sys
from pathlib import Path

record = json.loads(Path(sys.argv[1]).read_text())
enclave_id = record.get("EnclaveID", "")
if not re.fullmatch(r"i-[0-9a-f]+-enc[0-9a-f]+", enclave_id):
    raise SystemExit("Invalid dedicated enclave ID; inspect current enclave list manually")
if record.get("EnclaveCID") != 16:
    raise SystemExit("Unexpected enclave CID; refusing shutdown")
subprocess.run(["nitro-cli", "terminate-enclave", "--enclave-id", enclave_id], check=True, timeout=30)
