"""Fixed Base-native USDC payout transport; no configurable chain/token/target."""
import re
import threading
from urllib.parse import urlsplit
from .common import Rejected, address, integer, opaque_id, require, fields
from .epoch import CHAIN_ID, USDC_ADDRESS, DEPLOYER_REFUND_ADDRESS
from .policy import REWARDS, MAX_BUDGET

TRANSFER_SELECTOR = bytes.fromhex("a9059cbb")
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
MAX_FEE_WEI = 10_000_000_000
MAX_PRIORITY_FEE_WEI = 100_000_000
MAX_GAS = 100_000
MIN_CONFIRMATIONS = 2


def _quantity(value):
    require(isinstance(value, str) and re.fullmatch(r"0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)", value), "rpc_response_invalid")
    result = int(value, 16)
    require(result < 2**256, "rpc_response_invalid")
    return result


def _hash(value):
    require(isinstance(value, str) and re.fullmatch(r"0x[0-9a-fA-F]{64}", value), "rpc_response_invalid")
    return value.lower()


def transfer_data(recipient, reward_minor):
    recipient = address(recipient)
    require(type(reward_minor) is int and reward_minor in REWARDS, "invalid_reward")
    return TRANSFER_SELECTOR + bytes.fromhex(recipient[2:]).rjust(32,b"\0") + reward_minor.to_bytes(32,"big")


def refund_data(amount):
    integer(amount,1,MAX_BUDGET,"invalid_refund")
    return TRANSFER_SELECTOR + bytes.fromhex(DEPLOYER_REFUND_ADDRESS[2:]).rjust(32,b"\0") + amount.to_bytes(32,"big")


def _rlp_integer(raw):
    require(isinstance(raw, bytes) and len(raw) <= 32 and (not raw or raw[0] != 0), "invalid_transaction")
    return int.from_bytes(raw,"big")


class BaseUSDCPayoutTransport:
    """Injected RPC must terminate verified HTTPS TLS inside the enclave.

    rpc.endpoint is a deployment-pinned HTTPS URL; rpc.call(method,params) returns
    only JSON-RPC result and must reject redirects, wrong response IDs, error objects,
    oversized responses and TLS failures. No contributor may choose the RPC route.
    Rpc assertions are trusted chain observations, not cryptographic chain proofs.
    Epoch sign_transaction owns an unexported boot-only signer and pause guard.
    """
    def __init__(self, epoch, rpc, *, pinned_rpc_url):
        try:
            parsed = urlsplit(pinned_rpc_url)
            require(parsed.scheme == "https" and parsed.hostname and parsed.username is None and parsed.password is None
                    and not parsed.fragment and parsed.port in (None,443), "payout_rpc_invalid")
        except (ValueError, TypeError):
            raise Rejected("payout_rpc_invalid") from None
        require(getattr(rpc,"endpoint",None) == pinned_rpc_url, "payout_rpc_invalid")
        self.epoch, self.rpc = epoch, rpc
        self._lock, self._signed_jobs, self._next_nonce, self._known = threading.RLock(), {}, None, {}
        self._refund = None
        self.durable=getattr(epoch,'durable',False)
        if self.durable:self._restore_payments()

    def _restore_payments(self):
        for row in self.epoch.ledger.payment_rows():
            if row['signed_tx'] is not None:
                signed=bytes.fromhex(row['signed_tx']);tx_id=row['tx_id']
                require(self.validate(signed,tx_id,row['recipient'],row['reward']),'state_integrity')
                self._known[tx_id]=(signed,row['recipient'],row['reward'])
                self._signed_jobs[row['id']]=(signed,tx_id,row['recipient'],row['reward'])
        state=self.epoch.ledger.retirement_status()
        if state['state'] in {'refund_pending','refunded'} and state['transactionId'] is not None:
            signed,tx_id,amount=self.epoch.ledger.refund_identity()
            require(self.validate_refund(signed,tx_id,amount),'state_integrity')
            self._refund=(signed,tx_id,amount);self._known[tx_id]=(signed,DEPLOYER_REFUND_ADDRESS,amount)

    def check_continuity(self,*,bootstrap=False):
        self._chain()
        latest=_quantity(self._call('eth_getTransactionCount',[self.epoch.wallet,'latest']))
        pending=_quantity(self._call('eth_getTransactionCount',[self.epoch.wallet,'pending']))
        if not self.durable:return
        state=self.epoch.ledger.runtime_state()
        initial=self.epoch._anchor.config['initialWalletNonce']
        witness=state.get('nonceWitness',initial)
        require(initial<=latest<=pending<=witness,'payout_nonce_conflict')
        if bootstrap:require(latest==pending==initial and self.funding_balances()[0]==0,'state_bootstrap_wallet_used')
        # Every consumed/reserved nonce must have a known matching transaction.
        intents=[]
        for row in self.epoch.ledger.payment_rows():
            if row['payout_intent'] is not None:
                import json
                intent=json.loads(row['payout_intent']);nonce=intent['nonce']
                if row['state']=='paid':require(nonce<latest,'payout_nonce_conflict')
                if nonce<pending:
                    require(row['signed_tx'] is not None,'payout_nonce_conflict')
                if nonce<latest:
                    require(row['tx_id'] is not None,'payout_nonce_conflict')
                    self._continuity_receipt(row['tx_id'],row['recipient'],row['reward'])
                intents.append(nonce)
        refund=state.get('refundIntent')
        if refund is not None:
            if refund['nonce']<pending:require(self._refund is not None,'payout_nonce_conflict')
            if refund['nonce']<latest:
                require(self._refund is not None,'payout_nonce_conflict')
                self._continuity_receipt(self._refund[1],DEPLOYER_REFUND_ADDRESS,self._refund[2])
            intents.append(refund['nonce'])
        require(sorted(intents)==list(range(initial,witness)),'payout_nonce_conflict')

    def _continuity_receipt(self,tx_id,recipient,amount):
        require(tx_id in self._known and self._known[tx_id][1:]==(recipient,amount),'payout_nonce_conflict')
        if self._confirmed(tx_id,recipient,amount):return
        # A known exact signed transfer can be missing on a lagging RPC backend,
        # or still below required depth. Present mismatches remain fatal above.
        # Never sign a new intent yet; bounded settlement retries this same job.
        raise Rejected('payout_confirmation_pending')

    def preflight_recipient(self,recipient,amount):
        self._chain()
        calldata=transfer_data(recipient,amount)
        # No nonce reservation or KMS signing. Reject deterministic transfer/gas
        # failures before a paid grade creates an entitlement.
        self._build_transaction(calldata,0)

    def _intent(self,calldata,job_id=None):
        self.check_continuity()
        state=self.epoch.ledger.runtime_state()
        old=self.epoch.ledger.payout_intent(job_id) if job_id is not None else state.get('refundIntent')
        if old is not None:
            require(old['data']=='0x'+calldata.hex(),'payout_identity_mismatch')
            return {**old,'data':bytes.fromhex(old['data'][2:])}
        nonce=state.get('nonceWitness',self.epoch._anchor.config['initialWalletNonce'])
        # An unsigned prior intent must finish before allocating another nonce.
        for row in self.epoch.ledger.payment_rows():
            require(row['payout_intent'] is None or row['signed_tx'] is not None,'payout_intent_pending')
        require(state.get('refundIntent') is None,'payout_intent_pending')
        transaction=self._build_transaction(calldata,nonce)
        encoded={**transaction,'data':'0x'+calldata.hex()}
        if job_id is not None:self.epoch.ledger.prepare_intent(job_id,encoded)
        else:self.epoch.ledger.update_runtime({'refundIntent':encoded,'nonceWitness':nonce+1})
        return transaction

    def _call(self, method, params):
        try:
            return self.rpc.call(method,params)
        except Rejected:
            raise
        except Exception:
            raise Rejected("payout_rpc_unavailable") from None

    def _chain(self):
        require(_quantity(self._call("eth_chainId",[])) == CHAIN_ID,"payout_chain_mismatch")

    def funding_balances(self):
        self._chain()
        data = "0x70a08231" + self.epoch.wallet[2:].rjust(64,"0")
        usdc = self._call("eth_call",[{"to":USDC_ADDRESS,"data":data},"latest"])
        require(isinstance(usdc,str) and re.fullmatch(r"0x[0-9a-fA-F]{64}",usdc),"rpc_response_invalid")
        gas = _quantity(self._call("eth_getBalance",[self.epoch.wallet,"latest"]))
        return int(usdc,16),gas

    def sign(self, job_id, recipient, reward_minor):
        with self._lock, self.epoch.payment_guard():
            self.epoch.require_active()
            opaque_id(job_id)
            calldata = transfer_data(recipient,reward_minor)
            recipient = address(recipient)
            if job_id in self._signed_jobs:
                signed,tx_id,old_recipient,old_amount = self._signed_jobs[job_id]
                require(old_recipient == recipient and old_amount == reward_minor,"payout_identity_mismatch")
                return signed,tx_id
            signed,tx_id = self._sign_calldata(calldata,job_id=job_id)
            require(self.validate(signed,tx_id,recipient,reward_minor),"invalid_transaction")
            self._signed_jobs[job_id]=(signed,tx_id,recipient,reward_minor)
            self._known[tx_id]=(signed,recipient,reward_minor)
            return signed,tx_id

    def _build_transaction(self,calldata,nonce):
        require(nonce < 2**64,"rpc_response_invalid")
        latest=self._call("eth_getBlockByNumber",["latest",False])
        require(isinstance(latest,dict),"rpc_response_invalid")
        base_fee=_quantity(latest.get("baseFeePerGas"))
        priority=min(_quantity(self._call("eth_maxPriorityFeePerGas",[])),MAX_PRIORITY_FEE_WEI)
        max_fee=base_fee*2+priority
        require(0<max_fee<=MAX_FEE_WEI,"payout_fee_limit")
        from eth_utils import to_checksum_address
        estimated=_quantity(self._call("eth_estimateGas",[{"from":self.epoch.wallet,"to":USDC_ADDRESS,
                            "value":"0x0","data":"0x"+calldata.hex()}]))
        require(21000<=estimated<=MAX_GAS,"payout_gas_limit")
        return {"type":2,"chainId":CHAIN_ID,"nonce":nonce,"to":to_checksum_address(USDC_ADDRESS),
                "value":0,"data":calldata,"gas":min(MAX_GAS,(estimated*12+9)//10),
                "maxFeePerGas":max_fee,"maxPriorityFeePerGas":priority,"accessList":[]}

    def _sign_calldata(self,calldata,*,retirement=False,job_id=None):
        self._chain()
        if self.durable:transaction=self._intent(calldata,None if retirement else job_id)
        else:
            pending_nonce=_quantity(self._call("eth_getTransactionCount",[self.epoch.wallet,"pending"]))
            nonce=pending_nonce if self._next_nonce is None else max(pending_nonce,self._next_nonce)
            transaction=self._build_transaction(calldata,nonce)
        signed_result=(self.epoch.sign_retirement_transaction(transaction) if retirement
                       else self.epoch.sign_transaction(transaction))
        signed=bytes(signed_result.raw_transaction);tx_id="0x"+bytes(signed_result.hash).hex()
        self._next_nonce=transaction['nonce']+1
        return signed,tx_id

    def sign_refund(self,amount):
        with self._lock,self.epoch.retirement_guard():
            calldata=refund_data(amount)
            if self._refund is not None:
                signed,tx_id,old_amount=self._refund
                require(amount == old_amount,"refund_identity_mismatch")
                return signed,tx_id
            signed,tx_id=self._sign_calldata(calldata,retirement=True)
            require(self.validate_refund(signed,tx_id,amount),"invalid_refund")
            self._refund=(signed,tx_id,amount)
            self._known[tx_id]=(signed,DEPLOYER_REFUND_ADDRESS,amount)
            return signed,tx_id

    def validate_refund(self,signed,tx_id,amount):
        return self._validate(signed,tx_id,DEPLOYER_REFUND_ADDRESS,amount,retirement=True)

    def validate(self,signed,tx_id,recipient,reward_minor):
        return self._validate(signed,tx_id,recipient,reward_minor)

    def _validate(self, signed, tx_id, recipient, reward_minor,*,retirement=False):
        try:
            import rlp
            from eth_account import Account
            from eth_utils import keccak
            require(isinstance(signed,bytes) and 1 < len(signed) <= 1024 and signed[0] == 2,"invalid_transaction")
            require(_hash(tx_id) == "0x"+keccak(signed).hex(),"invalid_transaction")
            decoded = rlp.decode(signed[1:],strict=True)
            require(isinstance(decoded,list) and len(decoded)==12,"invalid_transaction")
            chain,nonce,priority,fee,gas = map(_rlp_integer,decoded[:5])
            require(chain == CHAIN_ID and nonce < 2**64 and priority <= MAX_PRIORITY_FEE_WEI and priority <= fee
                    and 0 < fee <= MAX_FEE_WEI and 21000 <= gas <= MAX_GAS,"invalid_transaction")
            calldata=refund_data(reward_minor) if retirement else transfer_data(recipient,reward_minor)
            require(not retirement or address(recipient) == DEPLOYER_REFUND_ADDRESS,"invalid_refund")
            require(decoded[5] == bytes.fromhex(USDC_ADDRESS[2:]) and _rlp_integer(decoded[6]) == 0
                    and decoded[7] == calldata and decoded[8] == [],"invalid_transaction")
            require(_rlp_integer(decoded[9]) in (0,1) and _rlp_integer(decoded[10]) > 0 and _rlp_integer(decoded[11]) > 0,
                    "invalid_transaction")
            require(Account.recover_transaction(signed).lower() == self.epoch.wallet,"invalid_transaction")
            return True
        except Exception:
            return False

    def broadcast(self, signed, tx_id):
        with self._lock, self.epoch.payment_guard():
            self.epoch.require_active()
            self._chain()
            if self.durable:
                self.epoch.ledger.assert_signed_payment(signed,tx_id)
            require(tx_id in self._known and self._known[tx_id][0] == signed,"payout_identity_mismatch")
            _,recipient,amount = self._known[tx_id]
            require(self.validate(signed,tx_id,recipient,amount),"invalid_transaction")
            result = self._call("eth_sendRawTransaction",["0x"+signed.hex()])
            require(_hash(result) == tx_id,"payout_identity_mismatch")

    def broadcast_refund(self,signed,tx_id):
        with self._lock,self.epoch.retirement_guard():
            self._chain()
            if self.durable:
                require(self.epoch.ledger.refund_identity()[:2]==(signed,tx_id),'refund_identity_mismatch')
            require(self._refund is not None and self._refund[:2] == (signed,tx_id),"refund_identity_mismatch")
            require(self.validate_refund(signed,tx_id,self._refund[2]),"invalid_refund")
            result=self._call("eth_sendRawTransaction",["0x"+signed.hex()])
            require(_hash(result) == tx_id,"refund_identity_mismatch")

    def confirmed_refund(self,tx_id,amount):
        integer(amount,1,MAX_BUDGET,"invalid_refund")
        return self._confirmed(tx_id,DEPLOYER_REFUND_ADDRESS,amount)

    def confirmed(self,tx_id,recipient,reward_minor):
        require(type(reward_minor) is int and reward_minor in REWARDS,"invalid_reward")
        return self._confirmed(tx_id,recipient,reward_minor)

    def _confirmed(self, tx_id, recipient, reward_minor,*,minimum_confirmations=MIN_CONFIRMATIONS):
        with self._lock:
            self._chain()
            tx_id,recipient = _hash(tx_id),address(recipient)
            receipt = self._call("eth_getTransactionReceipt",[tx_id])
            if receipt is None: return False
            require(isinstance(receipt,dict) and _hash(receipt.get("transactionHash"))==tx_id,"rpc_response_invalid")
            require(_quantity(receipt.get("status")) == 1,"payout_transaction_failed")
            require(address(receipt.get("from"))==self.epoch.wallet and address(receipt.get("to"))==USDC_ADDRESS,
                    "payout_receipt_mismatch")
            block_number,block_hash = _quantity(receipt.get("blockNumber")),_hash(receipt.get("blockHash"))
            latest = _quantity(self._call("eth_blockNumber",[]))
            block = self._call("eth_getBlockByNumber",[hex(block_number),False])
            if block is not None:
                require(isinstance(block,dict) and _hash(block.get("hash"))==block_hash,"payout_receipt_reorg")
            logs = receipt.get("logs")
            require(isinstance(logs,list) and len(logs)<=100,"rpc_response_invalid")
            expected_topics=[TRANSFER_TOPIC,"0x"+self.epoch.wallet[2:].rjust(64,"0"),"0x"+recipient[2:].rjust(64,"0")]
            matches=[]
            for log in logs:
                if not isinstance(log,dict): continue
                if isinstance(log.get("address"),str) and log["address"].lower()==USDC_ADDRESS:
                    topics=log.get("topics")
                    if isinstance(topics,list) and [str(topic).lower() for topic in topics]==expected_topics:
                        require(log.get("removed",False) is False and _hash(log.get("transactionHash"))==tx_id
                                and _hash(log.get("blockHash"))==block_hash,"payout_receipt_mismatch")
                        data=log.get("data")
                        require(isinstance(data,str) and re.fullmatch(r"0x[0-9a-fA-F]{64}",data),"rpc_response_invalid")
                        matches.append(int(data,16))
            require(matches == [reward_minor],"payout_receipt_mismatch")
            if block is None:
                if self.durable and tx_id in self._known:raise Rejected('payout_confirmation_pending')
                raise Rejected('payout_receipt_reorg')
            return latest >= block_number+minimum_confirmations-1
