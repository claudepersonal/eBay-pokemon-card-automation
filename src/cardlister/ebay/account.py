"""Verify the seller account's listing prerequisites via the Sell Account API.

Publishing an offer requires the account to be opted into Business Policies and to have
a payment, return, and fulfillment policy plus an inventory location. We can't reliably
create all of these programmatically (they depend on the seller's real settings), so we
verify and report what's missing — the UI surfaces it as a blocking checklist.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cardlister.ebay.client import EbayClient

_ACCOUNT_BASE = "/sell/account/v1"
_BUSINESS_POLICIES_PROGRAM = "SELLING_POLICY_MANAGEMENT"


@dataclass
class AccountStatus:
    fulfillment_policy_id: str | None = None
    payment_policy_id: str | None = None
    return_policy_id: str | None = None
    merchant_location_key: str | None = None
    opted_in_business_policies: bool = False
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def _first_id(
    client: EbayClient,
    path: str,
    list_key: str,
    id_key: str,
    *,
    params: dict[str, str] | None = None,
) -> str | None:
    body = client.get(f"{client.api_base}{_ACCOUNT_BASE}{path}", params=params).json()
    items = body.get(list_key) or []
    return items[0].get(id_key) if items else None


def verify_account(client: EbayClient, marketplace_id: str) -> AccountStatus:
    """Fetch policy IDs + location key and record any missing prerequisites."""
    status = AccountStatus()
    market = {"marketplace_id": marketplace_id}

    programs = client.get(f"{client.api_base}{_ACCOUNT_BASE}/program/get_opted_in_programs").json()
    program_types = {p.get("programType") for p in programs.get("programs", [])}
    status.opted_in_business_policies = _BUSINESS_POLICIES_PROGRAM in program_types
    if not status.opted_in_business_policies:
        status.problems.append(
            "Account is not opted into Business Policies (opt in under My eBay > Account)."
        )

    status.fulfillment_policy_id = _first_id(
        client, "/fulfillment_policy", "fulfillmentPolicies", "fulfillmentPolicyId", params=market
    )
    if not status.fulfillment_policy_id:
        status.problems.append("No fulfillment (shipping) policy found.")

    status.payment_policy_id = _first_id(
        client, "/payment_policy", "paymentPolicies", "paymentPolicyId", params=market
    )
    if not status.payment_policy_id:
        status.problems.append("No payment policy found.")

    status.return_policy_id = _first_id(
        client, "/return_policy", "returnPolicies", "returnPolicyId", params=market
    )
    if not status.return_policy_id:
        status.problems.append("No return policy found.")

    status.merchant_location_key = _first_id(
        client, "/location", "locations", "merchantLocationKey"
    )
    if not status.merchant_location_key:
        status.problems.append("No inventory location found (create one before listing).")

    return status
