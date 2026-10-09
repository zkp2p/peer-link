"""Ethereum type-2 signing through an injected KMS broker; no private key custody.

The broker signs the supplied Keccak digest using KMS MessageType=DIGEST and
ECDSA_SHA_256. That mode skips hashing: the algorithm's SHA-256 name does not
change Ethereum's already-computed 32-byte signing digest. Responses are untrusted
until verified against the measured wallet. KMS/IAM operator recovery authority
is separate from enclave policy enforcement; this is not exclusive TEE custody.
"""
import base64
import re
from typing import NamedTuple

import rlp
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from eth_keys import keys
from eth_utils import keccak, to_checksum_address

from .common import Rejected, address, fields, integer, require

SECP256K1_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
KEY_ARN = re.compile(r"arn:(?:aws|aws-us-gov|aws-cn):kms:[a-z]{2}(?:-[a-z]+)+-[0-9]+:[0-9]{12}:key/"
                     r"(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|mrk-[0-9a-f]{32})")
TRANSACTION_FIELDS = {"type", "chainId", "nonce", "to", "value", "data", "gas", "maxFeePerGas",
                      "maxPriorityFeePerGas", "accessList"}


class SignedTransaction(NamedTuple):
    raw_transaction: bytes
    hash: bytes


def _base64(value, maximum):
    require(isinstance(value, str) and 0 < len(value) <= ((maximum + 2) // 3) * 4, "kms_response_invalid")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        raise Rejected("kms_response_invalid") from None
    require(0 < len(decoded) <= maximum and base64.b64encode(decoded).decode() == value, "kms_response_invalid")
    return decoded


def _unsigned_fields(transaction):
    # Local imports permit BootEpoch to select this signer without import cycles.
    from .epoch import CHAIN_ID, USDC_ADDRESS, DEPLOYER_REFUND_ADDRESS
    from .eth_payout import TRANSFER_SELECTOR, MAX_FEE_WEI, MAX_PRIORITY_FEE_WEI, MAX_GAS
    from .policy import REWARDS, MAX_BUDGET
    fields(transaction, TRANSACTION_FIELDS)
    require(type(transaction["type"]) is int and transaction["type"] == 2
            and type(transaction["chainId"]) is int and transaction["chainId"] == CHAIN_ID
            and address(transaction["to"]) == USDC_ADDRESS
            and type(transaction["value"]) is int and transaction["value"] == 0
            and type(transaction["accessList"]) is list and transaction["accessList"] == [], "kms_transaction_invalid")
    nonce = integer(transaction["nonce"], 0, 2**64-1, "kms_transaction_invalid")
    gas = integer(transaction["gas"], 21000, MAX_GAS, "kms_transaction_invalid")
    fee = integer(transaction["maxFeePerGas"], 1, MAX_FEE_WEI, "kms_transaction_invalid")
    priority = integer(transaction["maxPriorityFeePerGas"], 0, min(fee, MAX_PRIORITY_FEE_WEI), "kms_transaction_invalid")
    data = transaction["data"]
    require(isinstance(data, bytes) and len(data) == 68 and data[:4] == TRANSFER_SELECTOR
            and data[4:16] == b"\0" * 12, "kms_transaction_invalid")
    recipient = address("0x" + data[16:36].hex())
    amount = int.from_bytes(data[36:], "big")
    require(amount in REWARDS or (recipient == DEPLOYER_REFUND_ADDRESS and 1 <= amount <= MAX_BUDGET),
            "kms_transaction_invalid")
    return [CHAIN_ID, nonce, priority, fee, gas, bytes.fromhex(USDC_ADDRESS[2:]), 0, data, []]


class KmsSigner:
    """exchange receives/returns bounded protocol dictionaries over a pinned broker.

    Only the key ARN and public wallet are configured here. Never accept a private
    key, AWS credential, endpoint override, alias, or a broker-selected wallet.
    The caller retains signed bytes before broadcast and handles nonce/idempotency.
    """
    def __init__(self, key_id, expected_wallet, exchange):
        require(isinstance(key_id, str) and len(key_id) <= 256 and KEY_ARN.fullmatch(key_id), "kms_key_invalid")
        self.key_id = key_id
        self.address = to_checksum_address(address(expected_wallet))
        require(callable(exchange), "kms_broker_invalid")
        self._exchange = exchange

    def sign_transaction(self, transaction):
        unsigned = _unsigned_fields(transaction)
        signing_digest = keccak(b"\x02" + rlp.encode(unsigned))
        try:
            response = self._exchange({"version": 1, "keyId": self.key_id, "digest": signing_digest.hex()})
        except Exception:
            raise Rejected("kms_broker_unavailable") from None
        if (isinstance(response,dict) and set(response)=={"version","error"}
                and type(response["version"]) is int and response["version"]==1
                and response["error"]=="kms_unavailable"):
            raise Rejected("kms_broker_unavailable")
        fields(response, {"version", "keyId", "publicKey", "signature"})
        require(type(response["version"]) is int and response["version"] == 1
                and response["keyId"] == self.key_id, "kms_response_invalid")
        public_der, signature_der = _base64(response["publicKey"], 200), _base64(response["signature"], 72)
        try:
            public = serialization.load_der_public_key(public_der)
            require(isinstance(public, ec.EllipticCurvePublicKey) and isinstance(public.curve, ec.SECP256K1),
                    "kms_public_key_invalid")
            require(public.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
                    == public_der, "kms_public_key_invalid")
            public_bytes = public.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)[1:]
            expected_public = keys.PublicKey(public_bytes)
            require(expected_public.to_checksum_address() == self.address, "kms_wallet_mismatch")
            r, s = utils.decode_dss_signature(signature_der)
            require(utils.encode_dss_signature(r, s) == signature_der
                    and 0 < r < SECP256K1_ORDER and 0 < s < SECP256K1_ORDER, "kms_signature_invalid")
            public.verify(signature_der, signing_digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
            s = min(s, SECP256K1_ORDER - s)
            parities = []
            for parity in (0, 1):
                try:
                    recovered = keys.Signature(vrs=(parity, r, s)).recover_public_key_from_msg_hash(signing_digest)
                    if recovered == expected_public:
                        parities.append(parity)
                except Exception:
                    continue
            require(len(parities) == 1, "kms_signature_invalid")
        except Rejected:
            raise
        except Exception:
            raise Rejected("kms_signature_invalid") from None
        signed = b"\x02" + rlp.encode(unsigned + [parities[0], r, s])
        return SignedTransaction(signed, keccak(signed))
