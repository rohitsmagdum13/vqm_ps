"""Quick script to describe Vendor_Account__c fields in Salesforce.

Prints all field names on the custom object so we know the exact
API names to use in SOQL queries and DML operations.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from simple_salesforce import Salesforce

load_dotenv()

sf = Salesforce(
    username=os.environ["SALESFORCE_USERNAME"],
    password=os.environ["SALESFORCE_PASSWORD"],
    security_token=os.environ["SALESFORCE_SECURITY_TOKEN"],
    consumer_key=os.environ["SALESFORCE_CONSUMER_KEY"],
    consumer_secret=os.environ["SALESFORCE_CONSUMER_SECRET"],
)

# Describe Vendor_Account__c
desc = sf.Vendor_Account__c.describe()

print("=== Vendor_Account__c Fields ===")
print(f"{'API Name':<40} {'Label':<35} {'Type':<15} {'Custom?'}")
print("-" * 100)

for field in sorted(desc["fields"], key=lambda f: f["name"]):
    print(f"{field['name']:<40} {field['label']:<35} {field['type']:<15} {field['custom']}")
