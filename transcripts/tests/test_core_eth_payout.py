"""Fixed synthetic signing and RPC fixtures; no network calls or transfers."""
import copy
import unittest
from contextlib import contextmanager
from eth_account import Account
from eth_utils import keccak
from transcripts.common import Rejected
from transcripts.epoch import CHAIN_ID,USDC_ADDRESS
from transcripts.eth_payout import BaseUSDCPayoutTransport,TRANSFER_TOPIC,transfer_data

RECIPIENT="0x"+"2"*40
TXID="0x"+"a"*64
BLOCKHASH="0x"+"b"*64


class SyntheticEpoch:
    def __init__(self):
        self.account=Account.from_key((1).to_bytes(32,"big"))
        self.wallet=self.account.address.lower();self.active=True;self.signs=0
    def require_active(self):
        if not self.active: raise Rejected("payout_paused")
    @contextmanager
    def payment_guard(self):
        self.require_active(); yield
    def sign_transaction(self,transaction):
        self.require_active();self.signs+=1
        return self.account.sign_transaction(transaction)


class SyntheticRPC:
    endpoint="https://rpc.example"
    chain=CHAIN_ID;nonce=7;base_fee=100_000_000;estimated_gas=60000;latest=101;receipt=None
    def __init__(self): self.calls=[];self.sent=[]
    def call(self,method,params):
        self.calls.append((method,params))
        if method=="eth_chainId": return hex(self.chain)
        if method=="eth_getTransactionCount": return hex(self.nonce)
        if method=="eth_maxPriorityFeePerGas": return hex(10000)
        if method=="eth_estimateGas": return hex(self.estimated_gas)
        if method=="eth_getBlockByNumber": return {"baseFeePerGas":hex(self.base_fee),"hash":BLOCKHASH}
        if method=="eth_blockNumber": return hex(self.latest)
        if method=="eth_sendRawTransaction":
            self.sent.append(params[0]);return "0x"+keccak(bytes.fromhex(params[0][2:])).hex()
        if method=="eth_getTransactionReceipt": return copy.deepcopy(self.receipt)
        if method=="eth_call": return "0x"+f"{50_000_000:064x}"
        if method=="eth_getBalance": return hex(10**12)
        raise AssertionError(method)


def receipt(wallet, **changes):
    result={"transactionHash":TXID,"status":"0x1","from":wallet,"to":USDC_ADDRESS,
            "blockNumber":"0x64","blockHash":BLOCKHASH,"logs":[
                {"address":USDC_ADDRESS,"topics":[TRANSFER_TOPIC,"0x"+wallet[2:].rjust(64,"0"),
                                                  "0x"+RECIPIENT[2:].rjust(64,"0")],
                 "data":"0x"+f"{10_000_000:064x}","removed":False,"transactionHash":TXID,"blockHash":BLOCKHASH}]}
    result.update(changes);return result


class EthPayoutTests(unittest.TestCase):
    def setUp(self):
        self.epoch,self.rpc=SyntheticEpoch(),SyntheticRPC()
        self.transport=BaseUSDCPayoutTransport(self.epoch,self.rpc,pinned_rpc_url=self.rpc.endpoint)
    def test_fixed_chain_usdc_transfer_and_signed_identity(self):
        signed,txid=self.transport.sign("job-1",RECIPIENT,10_000_000)
        self.assertTrue(self.transport.validate(signed,txid,RECIPIENT,10_000_000))
        self.assertFalse(self.transport.validate(signed,txid,"0x"+"3"*40,10_000_000))
        self.assertFalse(self.transport.validate(signed,txid,RECIPIENT,5_000_000))
        self.assertFalse(self.transport.validate(signed,"0x"+"f"*64,RECIPIENT,10_000_000))
        self.assertEqual(self.transport.sign("job-1",RECIPIENT,10_000_000),(signed,txid))
        self.assertEqual(self.epoch.signs,1)
        self.transport.broadcast(signed,txid);self.transport.broadcast(signed,txid)
        self.assertEqual(self.rpc.sent[0],self.rpc.sent[1])
        with self.assertRaisesRegex(Rejected,"payout_identity_mismatch"):
            self.transport.sign("job-1",RECIPIENT,5_000_000)
    def test_different_jobs_get_distinct_nonces_even_rpc_pending_lags(self):
        first=self.transport.sign("job-1",RECIPIENT,10_000_000)
        second=self.transport.sign("job-2",RECIPIENT,10_000_000)
        self.assertNotEqual(first,second)
        import rlp
        self.assertEqual(int.from_bytes(rlp.decode(first[0][1:])[1],"big"),7)
        self.assertEqual(int.from_bytes(rlp.decode(second[0][1:])[1],"big"),8)
    def test_pause_before_sign_and_broadcast(self):
        signed,txid=self.transport.sign("job-1",RECIPIENT,10_000_000)
        self.epoch.active=False
        with self.assertRaisesRegex(Rejected,"payout_paused"): self.transport.sign("job-2",RECIPIENT,10_000_000)
        with self.assertRaisesRegex(Rejected,"payout_paused"): self.transport.broadcast(signed,txid)
        self.assertEqual(self.rpc.sent,[])
    def test_wrong_chain_fee_and_gas_limits_prevent_sign(self):
        self.rpc.chain=1
        with self.assertRaisesRegex(Rejected,"payout_chain_mismatch"): self.transport.sign("job",RECIPIENT,10_000_000)
        self.rpc.chain=CHAIN_ID;self.rpc.base_fee=10**11
        with self.assertRaisesRegex(Rejected,"payout_fee_limit"): self.transport.sign("job",RECIPIENT,10_000_000)
        self.rpc.base_fee=100_000_000;self.rpc.estimated_gas=100001
        with self.assertRaisesRegex(Rejected,"payout_gas_limit"): self.transport.sign("job",RECIPIENT,10_000_000)
        self.assertEqual(self.epoch.signs,0)
    def test_decode_rejects_other_chain_target_value_and_calldata(self):
        from eth_utils import to_checksum_address
        base={"type":2,"chainId":CHAIN_ID,"nonce":0,"to":to_checksum_address(USDC_ADDRESS),"value":0,
              "data":transfer_data(RECIPIENT,10_000_000),"gas":60000,"maxFeePerGas":100000000,
              "maxPriorityFeePerGas":10000,"accessList":[]}
        for change in ({"chainId":1},{"to":to_checksum_address(RECIPIENT)},{"value":1},{"data":b"bad"},
                       {"maxFeePerGas":10**11},{"gas":100001}):
            transaction={**base,**change};signed=self.epoch.account.sign_transaction(transaction)
            self.assertFalse(self.transport.validate(bytes(signed.raw_transaction),"0x"+bytes(signed.hash).hex(),RECIPIENT,10_000_000))
    def test_exact_transfer_receipt_two_confirmations_and_canonical_block(self):
        self.assertFalse(self.transport.confirmed(TXID,RECIPIENT,10_000_000))
        self.rpc.receipt=receipt(self.epoch.wallet);self.rpc.latest=100
        self.assertFalse(self.transport.confirmed(TXID,RECIPIENT,10_000_000))
        self.rpc.latest=101
        self.assertTrue(self.transport.confirmed(TXID,RECIPIENT,10_000_000))
        self.rpc.receipt["blockHash"]="0x"+"c"*64
        with self.assertRaisesRegex(Rejected,"payout_receipt_reorg"): self.transport.confirmed(TXID,RECIPIENT,10_000_000)
    def test_failed_wrong_amount_wrong_token_removed_and_duplicate_logs_reject(self):
        for mutation in ("failed","amount","token","removed","duplicate","recipient"):
            self.rpc.receipt=receipt(self.epoch.wallet)
            log=self.rpc.receipt["logs"][0]
            if mutation=="failed": self.rpc.receipt["status"]="0x0"
            if mutation=="amount": log["data"]="0x"+f"{5_000_000:064x}"
            if mutation=="token": log["address"]="0x"+"3"*40
            if mutation=="removed": log["removed"]=True
            if mutation=="duplicate": self.rpc.receipt["logs"].append(copy.deepcopy(log))
            if mutation=="recipient": log["topics"][2]="0x"+"0"*24+"3"*40
            with self.assertRaises(Rejected): self.transport.confirmed(TXID,RECIPIENT,10_000_000)
    def test_https_pinned_rpc_and_actual_funding_queries(self):
        for url in ("http://rpc.example","https://other.example","https://rpc.example@evil.example"):
            with self.assertRaisesRegex(Rejected,"payout_rpc_invalid"):
                BaseUSDCPayoutTransport(self.epoch,self.rpc,pinned_rpc_url=url)
        self.assertEqual(self.transport.funding_balances(),(50_000_000,10**12))

if __name__ == "__main__": unittest.main()
