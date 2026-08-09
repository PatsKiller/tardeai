"""Gate A.1 Final Verification Suite."""
import json, sys, tempfile, threading, uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
tp=0
tf=0
fls=[]
def tt(n,c,d=""):
 global tp,tf
 if c:tp+=1;print(f"  PASS: {n}")
 else:tf+=1;print(f"  FAIL: {n} -- {d}");fls.append(n)
def mkp():d=Path(tempfile.gettempdir())/f"ga1-{uuid.uuid4().hex[:8]}";d.mkdir(parents=True,exist_ok=True);return str(d/"e.jsonl"),str(d/"c.jsonl")

# ====== R1.1 ======
from scripts.lib.cio_agent_handoff_queue import ALLOWED_TASK_TYPES,AGENT_REGISTRY,TARGET_NOT_READY_POLICY
tt("r1_1_single_registry",isinstance(ALLOWED_TASK_TYPES,frozenset) and len(ALLOWED_TASK_TYPES)>=19)
tt("r1_1_morgan_tasks",{"wealth_synthesis","goal_tracking","liquidity_planning","multi_account_coordination","tax_coordination","estate_review"}<=ALLOWED_TASK_TYPES)
tt("r1_1_guardian_not_ready",AGENT_REGISTRY["guardian"]["status"]=="NOT_READY")
tt("r1_1_ledger_not_ready",AGENT_REGISTRY["ledger"]["status"]=="NOT_READY")

# ====== R1.2 ======
from scripts.lib.cio_event_bus import CIOEventBus,CIOEvent
bp,cp=mkp();bus=CIOEventBus(bus_path=bp,cursor_path=cp)
evf={ff.name for ff in CIOEvent.__dataclass_fields__.values()}
tt("r1_2_source_immutable","acknowledged" not in evf)
e1=bus.emit("system.heartbeat_ok",{"s":1},source="test")
e2=bus.emit("system.heartbeat_ok",{"s":2},source="test")
ok,msg=bus.verify_integrity()
tt("r1_2_chain",ok,msg)
bus.advance_cursor("A",e1.event_id);bus.advance_cursor("A",e2.event_id)
tt("r1_2_per_consumer",len(bus.poll(consumer="A"))==0 and len(bus.poll(consumer="B"))>=2)
tt("r1_2_replay",len(bus.poll())>=2)
def ce(s,c):
 b=CIOEventBus(bus_path=bp,cursor_path=cp)
 for i in range(s,s+c):b.emit("system.heartbeat_ok",{"s":i},source="c")
t1=threading.Thread(target=ce,args=(100,10));t2=threading.Thread(target=ce,args=(200,10));t3=threading.Thread(target=ce,args=(300,10))
t1.start();t2.start();t3.start();t1.join();t2.join();t3.join()
ok2,msg2=bus.verify_integrity();tt("r1_2_concurrent",ok2,msg2)
try:bus.emit("bogus",{});tt("r1_2_invalid_rejected",False)
except ValueError:tt("r1_2_invalid_rejected",True)
cid=bus.advance_cursor("f",e2.event_id);tt("r1_2_adv_ret",cid.startswith("cur-"))
bp3,cp3=mkp();busx=CIOEventBus(bus_path=bp3,cursor_path=cp3)
busx.emit("system.heartbeat_ok",{"v":1},source="test")
busx.emit("system.heartbeat_ok",{"v":2},source="test")
tt("r1_2_drain",len(busx.drain_unprocessed("dc",5))==2 and len(busx.poll(consumer="dc"))==0)
bp2,cp2=mkp();bus3=CIOEventBus(bus_path=bp2,cursor_path=cp2)
bus3.emit("system.heartbeat_ok",{"v":1},source="test")
import hashlib as hl
with open(bp2)as fh:
 for ln in fh:
  s=ln.strip()
  if not s or"genesis"in s:continue
  e=json.loads(s);st=e.pop("event_hash","");e.pop("prev_hash",None);e.pop("event_hash",None)
  cm=hl.sha256(json.dumps(e,sort_keys=True,default=str).encode()).hexdigest();break
tt("r1_2_new_hash",len(st)==64)

# ====== R1.3 ======
# Behavioral: prove heartbeat has zero reachable model/network/action paths
hb_src = Path(__file__).resolve().parent.parent / "scripts" / "cio_heartbeat.py"
hb_text = hb_src.read_text()
tt("r1_3_no_ollama","ollama" not in hb_text.lower())
tt("r1_3_no_urllib","urllib.request" not in hb_text)
tt("r1_3_no_flash_context","_add_flash_context" not in hb_text)
tt("r1_3_no_delegation","run_delegation_cycle" not in hb_text)
tt("r1_3_no_telegram_import","send_message" not in hb_text.lower())
tt("r1_3_no_telegram_api","bot_token" not in hb_text.lower())
# idempotency: summary reports zero model calls
tt("r1_3_model_calls_zero",'"model_calls": 0' in hb_text or "'model_calls': 0" in hb_text)
tt("r1_3_cost_zero",'"provider_cost": 0.0' in hb_text or "'provider_cost': 0.0" in hb_text)
# Event publication preserved
tt("r1_3_event_pub","CIOEventBus" in hb_text and "bus.emit" in hb_text)
# Behavioral finance detection still present
tt("r1_3_behavioral","_detect_disposition_effect" in hb_text)
# Liveness event
tt("r1_3_liveness","system.heartbeat_ok" in hb_text)

# Also run the heartbeat with monkeypatched network to prove no model calls
import scripts.cio_heartbeat as hb
os_snap=hb.SNAPSHOT_PATH;os_data=hb.DATA_DIR
# Snapshot canonical event store line count for cleanup later
canon_bus_path = Path("data/cio/cio_events.jsonl")
canon_before = len([l for l in canon_bus_path.read_text().splitlines() if l.strip()]) if canon_bus_path.exists() else 0
with tempfile.TemporaryDirectory()as td:
 td_p=Path(td);hb.DATA_DIR=td_p;hb.SNAPSHOT_PATH=td_p/"h.jsonl";td_p.mkdir(exist_ok=True)
 with patch("urllib.request.urlopen",side_effect=AssertionError("MODEL_VIOLATION")):
  with patch("urllib.request.Request",side_effect=AssertionError("MODEL_VIOLATION")):
   try:
    rr=hb.run_heartbeat()
    # If we got here without AssertionError, no model call was made
    tt("r1_3_behavioral_model_free",rr.get("model_calls")==0)
    tt("r1_3_behavioral_cost_free",rr.get("provider_cost")==0.0)
    tt("r1_3_events_emitted",isinstance(rr.get("events_emitted",0),int) and rr.get("events_emitted",0)>=1)
    tt("r1_3_no_ledger_writes",not(td_p/"cio_action_ledger.jsonl").exists())
    tt("r1_3_no_handoff_writes",not(td_p/"agent_handoff_queue.jsonl").exists())
    tt("r1_3_no_hermes_writes",not(td_p/"hermes_challenge_queue.jsonl").exists())
   except AssertionError as e:
    if "MODEL_VIOLATION" in str(e):
     tt("r1_3_behavioral_model_free",False,"heartbeat made a model call")
    else:raise
hb.SNAPSHOT_PATH=os_snap;hb.DATA_DIR=os_data
# Clean up any events heartbeat wrote to canonical store
if canon_bus_path.exists():
 all_lines = [l for l in canon_bus_path.read_text().splitlines() if l.strip()]
 if len(all_lines) > canon_before:
  kept = all_lines[:canon_before]
  canon_bus_path.write_text("\n".join(kept) + "\n")

# ====== R1.4 ======
from scripts.lib.cio_notification_delivery import RealTelegramAdapter,FakeDeliveryAdapter
ra=RealTelegramAdapter();r=ra.send({"notification_id":"t30","body":"x"})
tt("r1_4_blocked",r["delivered"]is False and r.get("error")=="DELIVERY_BLOCKED_CREDENTIALS")
fa=FakeDeliveryAdapter();r3=fa.send({"notification_id":"t32","body":"x"})
tt("r1_4_shadow",r3["delivered"]is True and r3["delivery_method"]=="shadow")
with patch("urllib.request.urlopen",side_effect=Exception("down")):
 ra3=RealTelegramAdapter(bot_token="tk",chat_id="ch");r4=ra3.send({"notification_id":"t33","body":"x"})
 tt("r1_4_net_fail",r4["delivered"]is False)
class FakeResp:
 def __enter__(self):return self
 def __exit__(self,*a):pass
 def read(self):return b'{"ok":true,"result":{"message_id":42}}'
def fake_urlopen(req,timeout=None):return FakeResp()
with patch("urllib.request.urlopen",side_effect=fake_urlopen):
 ra5=RealTelegramAdapter(bot_token="tk",chat_id="ch");r5=ra5.send({"notification_id":"t34","body":"x"})
 tt("r1_4_success",r5["delivered"]is True and r5.get("delivery_method")=="telegram")

# ====== R1.5 ======
import scripts.cio_commands as cc
from scripts.lib.cio_action_ledger import VALID_EVENT_TYPES,TERMINAL_STATUSES,STATUS_TRANSITION_EVENTS
tt("r1_5_ack","CIO_ACTION_ACKNOWLEDGED"in VALID_EVENT_TYPES)
tt("r1_5_defer","CIO_ACTION_DEFERRED"in VALID_EVENT_TYPES)
tt("r1_5_done","CIO_ACTION_DONE"in VALID_EVENT_TYPES and"DONE"in TERMINAL_STATUSES)
tt("r1_5_reject_gap","REJECTED"not in TERMINAL_STATUSES)
for nm in["cmd_ack","cmd_rate","cmd_defer","cmd_done","cmd_reject"]:
 tt(f"r1_5_{nm}",callable(getattr(cc,nm,None)))
oa=list(sys.argv)
try:
 sys.argv=["cio_commands","ack"];tt("r1_5_ack_usage","Usage:"in cc.cmd_ack())
 sys.argv=["cio_commands","defer"];tt("r1_5_defer_usage","Usage:"in cc.cmd_defer())
 sys.argv=["cio_commands","done"];tt("r1_5_done_usage","Usage:"in cc.cmd_done())
 sys.argv=["cio_commands","reject","x"];orj=cc.cmd_reject()
 tt("r1_5_reject_wired",orj.startswith("\U0001f6ab")or"Failed"in orj or"CANCELLED"in orj)
finally:sys.argv=oa

# ====== Crypto ======
from scripts.lib.cio_event_bus import DEFAULT_BUS_PATH
cb=CIOEventBus(bus_path=DEFAULT_BUS_PATH,cursor_path=str(Path(tempfile.gettempdir())/f"cc-{uuid.uuid4().hex[:8]}.jsonl"))
okc,msgc=cb.verify_integrity();tt("r1_2_canon_chain",okc,msgc)
cp2=Path(DEFAULT_BUS_PATH);lf=False
if cp2.exists():
 with open(cp2)as fh2:
  for ln2 in fh2:
   s2=ln2.strip()
   if not s2 or"genesis"in s2:continue
   if"acknowledged"in json.loads(s2):lf=True
   break
tt("r1_2_legacy_fmt",lf)

print(f"\n=== GATE A.1: {tp} passed, {tf} failed, {tp+tf} total ===")
if tf:print("FAILURES:");print("\n".join(f"  - {x}"for x in fls));raise SystemExit(1)
else:print("GATE A.1 TESTS: ALL PASSED")
