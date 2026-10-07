"""Cache plain results, never connections or open transactions. Exceptions are not cached."""

import streamlit as st

from . import data


@st.cache_data(ttl=60, max_entries=64, show_spinner=False)
def catalog(source):
    return data.catalog()


@st.cache_data(ttl=60, max_entries=128, show_spinner=False)
def fetch(source, view, context):
    return data.fetch(view, context)


def refresh():
    catalog.clear()
    fetch.clear()
