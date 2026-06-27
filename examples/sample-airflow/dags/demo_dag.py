"""Example Airflow DAG. The architecture scan is platform-agnostic — it flags the
deprecated-dataset reference below the same way it would in a Databricks notebook."""

# LAYER: marts
EXTRACT_SQL = """
SELECT * FROM staging.orders o
JOIN `legacy_dataset.customers` c ON c.id = o.cust_id
"""
