#!/usr/bin/env python3
"""
Focused live MCP reproduction script for POIDH Bounty #1495 (Base onChainId: 509).
Executes 4 public, stateless JSON-RPC read/prepare calls against
https://poidh.xyz/api/mcp using only the Python standard library:
  1. NOVEL-01: get_account on Ethereum Mainnet PoidhV3 core contract
     (0xE731dFadBFf20542E10D09D26Fc71445C70d4232) -> misclassified as accountType="user"
  2. NOVEL-01 Control: get_account on Base/Arbitrum PoidhV3 core contract
     (0x5555FA783936c260F77385B4e153b9725Fef1719) -> classified as accountType="protocol_contract"
  3. NOVEL-01 Downstream: get_account on Ethereum Mainnet claimant
     (0x5e4e5ea537ce7e79b8a0fc4f0cb520e9b8b5dae5) -> relatedUsers polluted with Mainnet PoidhV3
  4. NOVEL-07: prepare_create_bounty with amountEth = "9" * 65 (exceeding uint256 max)
     -> returns unsendable 276-bit hex transaction.value without validation error

Requires no credentials, private keys, or third-party packages.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

MCP_URL = "https://poidh.xyz/api/mcp"
WORK_DIR = Path(__file__).resolve().parent
REQUEST_LOG = WORK_DIR / "request_log.jsonl"
EVIDENCE_OUT = WORK_DIR / "focused-evidence.json"

MAINNET_V3_CONTRACT = "0xE731dFadBFf20542E10D09D26Fc71445C70d4232"
TYPO_MAP_KEY = "0xe731dfadbf20542e10d09d26fc71445c70d4232"
BASE_ARB_V3_CONTRACT = "0x5555FA783936c260F77385B4e153b9725Fef1719"
MAINNET_CLAIMANT = "0x5e4e5ea537ce7e79b8a0fc4f0cb520e9b8b5dae5"
UINT256_MAX = (1 << 256) - 1


def call_mcp_tool(req_id: int, tool_name: str, arguments: dict) -> dict:
  payload = {
      "jsonrpc": "2.0",
      "id": req_id,
      "method": "tools/call",
      "params": {
          "name": tool_name,
          "arguments": arguments,
      },
  }
  body = json.dumps(payload).encode("utf-8")
  req = urllib.request.Request(
      MCP_URL,
      data=body,
      headers={
          "Content-Type": "application/json",
          "Accept": "application/json, text/event-stream",
          "User-Agent": "poidh-bounty-1495-focused-repro/1.0",
      },
      method="POST",
  )
  t0 = time.time()
  status_code = None
  raw_text = ""
  try:
    with urllib.request.urlopen(req, timeout=20) as resp:
      status_code = resp.status
      raw_text = resp.read().decode("utf-8", errors="replace")
  except urllib.error.HTTPError as exc:
    status_code = exc.code
    raw_text = exc.read().decode("utf-8", errors="replace")
  elapsed_ms = round((time.time() - t0) * 1000, 1)

  log_entry = {
      "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
      "suite": "focused-reproduce.py",
      "method": "POST",
      "url": MCP_URL,
      "mcp_method": f"tools/call:{tool_name}",
      "status": status_code,
      "elapsed_ms": elapsed_ms,
  }
  with REQUEST_LOG.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps(log_entry) + "\n")

  rpc_obj = json.loads(raw_text)
  result = rpc_obj.get("result", {})
  is_error = bool(result.get("isError", False))
  structured = result.get("structuredContent")
  text_content = ""
  if result.get("content") and isinstance(result["content"], list):
    text_content = result["content"][0].get("text", "")
  if structured is None and text_content:
    try:
      structured = json.loads(text_content)
    except Exception:
      structured = None

  return {
      "http_status": status_code,
      "elapsed_ms": elapsed_ms,
      "isError": is_error,
      "structuredContent": structured,
      "text": text_content,
  }


def main() -> None:
  # 1. NOVEL-01: Ethereum Mainnet PoidhV3 contract classification
  mainnet_res = call_mcp_tool(
      1, "get_account", {"address": MAINNET_V3_CONTRACT}
  )
  mainnet_sc = mainnet_res["structuredContent"] or {}
  mainnet_profile = mainnet_sc.get("profile", {})
  mainnet_summary = mainnet_sc.get("summary", {})

  # 2. NOVEL-01 Control: Base/Arbitrum PoidhV3 contract classification
  base_res = call_mcp_tool(2, "get_account", {"address": BASE_ARB_V3_CONTRACT})
  base_sc = base_res["structuredContent"] or {}
  base_profile = base_sc.get("profile", {})
  base_summary = base_sc.get("summary", {})

  # 3. NOVEL-01 Downstream: Ethereum Mainnet claimant relatedUsers check
  claimant_res = call_mcp_tool(3, "get_account", {"address": MAINNET_CLAIMANT})
  claimant_sc = claimant_res["structuredContent"] or {}
  related_users = claimant_sc.get("relatedUsers", [])
  polluted_entries = [
      u
      for u in related_users
      if str(u.get("address", "")).lower() == MAINNET_V3_CONTRACT.lower()
  ]

  # 4. NOVEL-07: prepare_create_bounty with 65-digit ETH string (> uint256 max wei)
  overflow_amount_eth = "9" * 65
  overflow_res = call_mcp_tool(
      4,
      "prepare_create_bounty",
      {
          "chain": "base",
          "title": "uint256 bound test",
          "description": "testing parseEthAmount upper bound",
          "amountEth": overflow_amount_eth,
      },
  )
  overflow_sc = overflow_res["structuredContent"] or {}
  tx_obj = overflow_sc.get("transaction", {})
  tx_value_hex = tx_obj.get("value", "0x0")
  tx_value_int = int(tx_value_hex, 16)
  wallet_send_calls = overflow_sc.get("walletSendCalls", {})
  wsc_calls = wallet_send_calls.get("calls", [{}])
  wsc_value_hex = wsc_calls[0].get("value", "0x0") if wsc_calls else "0x0"

  novel_01_reproduced = (
      mainnet_profile.get("accountType") == "user"
      and mainnet_profile.get("isProtocolContract") is False
      and base_profile.get("accountType") == "protocol_contract"
      and base_profile.get("isProtocolContract") is True
      and len(polluted_entries) > 0
  )

  novel_07_reproduced = (
      overflow_res["isError"] is False and tx_value_int > UINT256_MAX
  )

  evidence = {
      "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
      "target_bounty": {
          "url": "https://poidh.xyz/base/bounty/1495",
          "chain": "base",
          "chainId": 8453,
          "frontendId": 1495,
          "onChainId": 509,
      },
      "source_commit": "bd3a3dbbae0143ef3e507b3b2b4ce9ba44a21de9",
      "mcp_endpoint": MCP_URL,
      "mcp_requests_made": 4,
      "findings": {
          "NOVEL-01": {
              "title": (
                  "39-hex-character typo in POIDH_PROTOCOL_CONTRACTS"
                  " misclassifies Ethereum Mainnet PoidhV3 contract as a normal"
                  " user and pollutes claimant relatedUsers"
              ),
              "reproduced": novel_01_reproduced,
              "source_location": "src/app/account/[address]/data/route.ts:35-60",
              "typo_key_in_map": TYPO_MAP_KEY,
              "typo_key_hex_length": len(TYPO_MAP_KEY) - 2,
              "actual_mainnet_v3_contract": MAINNET_V3_CONTRACT.lower(),
              "actual_contract_hex_length": len(MAINNET_V3_CONTRACT) - 2,
              "live_mainnet_v3_get_account": {
                  "http_status": mainnet_res["http_status"],
                  "isError": mainnet_res["isError"],
                  "profile": mainnet_profile,
                  "summary_subset": {
                      "nftsHeld": mainnet_summary.get("nftsHeld"),
                      "relatedUsers": mainnet_summary.get("relatedUsers"),
                  },
              },
              "live_base_v3_control_get_account": {
                  "http_status": base_res["http_status"],
                  "isError": base_res["isError"],
                  "profile": base_profile,
                  "summary_subset": {
                      "nftsHeld": base_summary.get("nftsHeld"),
                      "relatedUsers": base_summary.get("relatedUsers"),
                  },
              },
              "live_mainnet_claimant_pollution": {
                  "claimant_address": MAINNET_CLAIMANT,
                  "http_status": claimant_res["http_status"],
                  "polluted_relatedUsers_entries": polluted_entries,
              },
          },
          "NOVEL-07": {
              "title": (
                  "Missing uint256 upper bound in parseEthAmount allows"
                  " prepare_create_bounty to emit"
                  " unsendable >256-bit hex transaction values"
              ),
              "reproduced": novel_07_reproduced,
              "source_location": (
                  "src/mcp/transactions.ts:204-216, src/mcp/server.ts:313,346"
              ),
              "input_amountEth": overflow_amount_eth,
              "live_prepare_create_bounty": {
                  "http_status": overflow_res["http_status"],
                  "isError": overflow_res["isError"],
                  "transaction_value_hex": tx_value_hex,
                  "walletSendCalls_value_hex": wsc_value_hex,
                  "value_bit_length": tx_value_int.bit_length(),
                  "uint256_max_bit_length": 256,
                  "exceeds_uint256_max": tx_value_int > UINT256_MAX,
              },
          },
      },
  }

  with EVIDENCE_OUT.open("w", encoding="utf-8") as fh:
    json.dump(evidence, fh, indent=2)
    fh.write("\n")

  print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
  main()
