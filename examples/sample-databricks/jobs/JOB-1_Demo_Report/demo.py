# JOB: JOB-1 Demo Report
# TICKET: JOB-1
# PURPOSE: Daily demo report joining staging orders to the analytics customer view
# STATUS: ACTIVE
# LAST_UPDATED: 2026-06-01
import pandas as pd
QUERY = """
SELECT * FROM ANALYTICS.VW_CUSTOMER c
JOIN STAGING.ORDERS o ON o.cust_id = c.id
LEFT JOIN LEGACY_STORE.OLD_SNAPSHOT s ON s.id = c.id
"""
