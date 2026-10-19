# Two reproduced MCP data and input-validation defects

Bounty: [poidh Base #1495](https://poidh.xyz/base/bounty/1495) (contract bounty 509).
Research: QWE participant using Antigravity Gemini4Argon on a VPS; independently
reviewed and reproduced by the QWE supervisor. Wallet: W01,
`0xd29c790466675153A50DF7860B9EFDb689A21cDe`.

This submission contains **two findings**, additional to the existing reports
reviewed for this bounty. Novelty is assessed against those reports, not a claim
that nobody has ever observed this behavior. Both are data/input-validation
issues. No contract exploit or loss of funds is demonstrated.

## 1. Mainnet protocol contract is classified as a user

Pinned source: [account data route, lines35–60](https://github.com/picsoritdidnthappen/poidh-app/blob/bd3a3dbbae0143ef3e507b3b2b4ce9ba44a21de9/src/app/account/%5Baddress%5D/data/route.ts#L35).

The `POIDH_PROTOCOL_CONTRACTS` Map contains this malformed Mainnet key:

```
0xe731dfadbf20542e10d09d26fc71445c70d4232
```

It has 39 hex characters. The actual Mainnet core address has 40:

```
0xe731dfadbff20542e10d09d26fc71445c70d4232
```

The missing `f` prevents exact matching. We called public MCP `get_account` with
both the real Mainnet core and the Base core as a control.

| Observed account | Expected classification | Actual live classification |
| --- | --- | --- |
| Mainnet core `0xe731…4232` | `protocol_contract`, true | `profile.accountType: user`, `profile.isProtocolContract: false` |
| Base core `0x5555…1719` | `protocol_contract`, true | `profile.accountType: protocol_contract`, `profile.isProtocolContract: true` |

A third read of claimant `0x5e4e5ea537ce7e79b8a0fc4f0cb520e9b8b5dae5`
returns the Mainnet escrow contract in `relatedUsers`, labelled as a user, with
relationship `current_owner_of_profile_submitted_claim_nft`. This demonstrates
that the classification error also reaches the public relationship graph.

**Suggested fix:** correct the Map key by adding the missing `f`; preferably
derive protocol addresses from the canonical chain configuration. A regression
test should check that every configured core address is correctly classified.
This is an account-data defect, not an incorrect contract deployment.

## 2. ETH amount preparation accepts values larger than uint256

Pinned source: [parseEthAmount, lines204–216](https://github.com/picsoritdidnthappen/poidh-app/blob/bd3a3dbbae0143ef3e507b3b2b4ce9ba44a21de9/src/mcp/transactions.ts#L204).

We invoked unsigned `prepare_create_bounty` on Base with `amountEth` equal to
65 decimal nines. No `from` wallet or signature was supplied and no transaction
was sent. The MCP result returned `isError: false` and the following value:

```
0xd2d80db02aabd62bf50a3fa490c301900d6953169e1c7a1e7fffff21f494c589c0000
```

The integer is 276 bits, exceeding `2**256 - 1`. It appears in both
`transaction.value` and `walletSendCalls.calls[0].value`.

**Expected:** a validation error before returning transaction data.
**Actual:** an out-of-range unsigned transaction payload is prepared.
The source parser checks decimal syntax and positivity but lacks a uint256
upper bound. The live reproduction here covers `prepare_create_bounty`; related
call sites using the same parser are a source observation, not another live test.

**Suggested fix:** enforce `0 < wei <= maxUint256` after conversion, with boundary
tests for the maximum and maximum-plus-one. This is a minor preparation/UX defect;
it does not show that a wallet accepted or executed such a transaction.

## Reproduce and inspect evidence

Run `python3 reproduce.py` with Python standard library and network access.
It makes exactly four public MCP calls: three account reads and one unsigned
bounty preparation. No credentials, private keys, signatures or onchain writes
are used. Results are saved to `focused-evidence.json`; its observed timestamps
and `findings.*.reproduced` values are the evidence for this submission.
The attached evidence was also checked by an independent supervisor run.

The source commit reviewed is
`bd3a3dbbae0143ef3e507b3b2b4ce9ba44a21de9`. Live endpoints can change after the
observation; a later false reproduction result may indicate a fix or a response
change. This report does not claim a real-browser WebMCP test. Earlier broad
research drafts and synthetic helper experiments are excluded from the findings.
