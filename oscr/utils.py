"""
oscr.utils
~~~~~~~~~~

This module implements utility methods for the API.
"""

import re
from datetime import datetime
from logging import info
from statistics import mean
from time import strftime

from oscr.bias import FUNCTION_BIAS, TITLE_BIAS
from oscr.models import Account
from oscr.clients.discoverorg import DiscoverOrgClient
from oscr.clients.salesforce import SalesforceClient


def enrich(sfc: SalesforceClient, doc: DiscoverOrgClient, account: Account) -> None:
    """ Enriches a given account. 
    
    :param sfc: A `SalesforceClient` instance.
    :param doc: A `DiscoverOrgClient` instance.
    :param account: An `Account` object.
    """
    raw_info: dict = doc.get_company_info(account)
    company_info: str = format_company_info(raw_info) if raw_info else None

    sf_contacts: list = [c for c in sfc.get_contacts(account)]
    do_contacts: list = [c for c in doc.get_contacts(account)]

    names: list = [c.name for c in sf_contacts]
    emails: list = [c.email for c in sf_contacts]
    domains: list = [
        re.findall(r"@(\w.+)", c.email)[0] for c in sf_contacts if c.email
    ] + re.findall(
        r"^(?:https?://)?(?:[^@/\n]+@)?(?:www\.)?([^:/?\n]+)", account.domain or ""
    )

    contacts: list = _filter(
        [
            contact
            for contact in do_contacts
            if (
                contact.email
                and contact.email != ""
                and contact.name not in names
                and contact.email not in emails
                and re.findall(r"@(\w.+)", contact.email)[0] not in domains
            )
        ]
    )

    if contacts:
        sfc.upload_contacts(account, contacts)

    summary: str = format_enrichment_summary(sf_contacts, do_contacts, contacts)

    if company_info and summary:
        sfc.upload_notes(account, company_info, summary)

    if contacts and company_info and summary:
        sfc.complete_enrichment(account)


def _filter(contacts: list) -> list:
    """ Filters a given list of contacts for writing to Salesforce.

    This method uses the 'Scarce' selection algorithm. Documentation of
    this algorithm can be found in the `docs` section of the main OSCR repository.

    :param contacts: A `list` of `Contact` objects.
    :return: A filtered `list` of `Contact` objects.
    """
    for contact in contacts:
        for i, group in enumerate(TITLE_BIAS):
            for title in group:
                if title in contact.title.upper():
                    contact.rating = i
                    break

        for i, function in enumerate(FUNCTION_BIAS):
            if function in contact.title.upper():
                contact.priority = i
                break

    contacts: list = sorted(contacts, key=lambda c: c.rating + c.priority)
    contacts: list = contacts[: int(len(contacts) / 3)] if len(
        contacts
    ) >= 45 else contacts
    contacts: list = contacts[:100] if len(contacts) > 50 else contacts

    return contacts


def format_company_info(info_dict):
    """ Produces a field-friendly string from a dictionary of company data. 
    
    :param info_dict: A `dict` of company info produced by the 
                      `DiscoverOrgClient`'s `get_company_info` function.
    :return: A formatted `str` of company info.
    """
    overview: str = info_dict.get("description", "<i>Not found.</i>")
    size: str = info_dict.get("numEmployees", "<i>Not found.</i>")
    revenue: str = info_dict.get("revenue", "<i>Not found.</i>")
    location: dict = info_dict.get("location")
    headquarters: str = ", ".join(
        [
            location.get("city", "<i>N/A</i>"),
            location.get("stateProvinceRegion", "<i>N/A</i>"),
            location.get("countryName", "<i>N/A</i>"),
        ]
    )

    info_str: str = "<br>".join(
        [
            f"<b>Updated:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br>",
            f"<b>Overview:</b> {overview}",
            f"<b>Size:</b> {size:,}",
            f"<b>Revenue:</b> {revenue:,}",
            f"<b>Headquarters:</b> {headquarters}",
        ]
    )

    return info_str


def format_enrichment_summary(
    sf_contacts: list, do_contacts: list, contacts: list
) -> str:
    """ Produces a field-friendly string summarizing the enrichment process. 
    
    :param sf_contacts: A `list` of `Contact` objects produced by the
                        `SalesforceClient`'s `get_contacts` function.
    :param do_contacts: A `list` of `Contact` objects produced by the
                        `DiscoverOrgClient`'s `get_contacts` function.
    :param contacts: A `list` of the finalized filtered `Contact` objects.
    :return: A formatted `str` enrichment summary.
    """
    n_sf_contacts = len(sf_contacts)
    n_do_contacts = len(do_contacts)
    n_contacts_added = len(contacts)

    if len(contacts) > 0:
        avg_rating = round(mean([c.rating for c in contacts]), 2)
        avg_priority = round(mean([c.priority for c in contacts]), 2)
    else:
        avg_rating = "N/A"
        avg_priority = "N/A"

    summary = "<br>".join(
        [
            f"<b># of Contacts in Salesforce Before:</b> {n_sf_contacts}",
            f"<b># of Contacts in Salesforce After:</b> {n_sf_contacts + n_contacts_added}",
            f"<b># of Contact Available:</b> {n_do_contacts}",
            f"<b># of Contacts Added:</b> {n_contacts_added}",
            f"<b>Average Rating:</b> {avg_rating}",
            f"<b>Average Priority:</b> {avg_priority}",
            "<br><i>Rating and priority are the measures by which OSCR qualifies contacts. "
            "The lower the numbers, the better the quality of the contacts added.</i>",
            "<br><b>Contacts Added:</b>",
            ", ".join([contact.name for contact in contacts]),
        ]
    )

    return summary
