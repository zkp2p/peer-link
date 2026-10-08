"""Fixed Nitro entrypoint; host environment cannot select enclave mode or policy."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from transcripts.runtime import main

if __name__ == "__main__":
    # Nitro bootstrap does not preserve Docker's WORKDIR/PATH or pass runtime args.
    sys.argv = [sys.argv[0], "--vsock-port", "5100", "--egress-port", "5101"]
    main()
