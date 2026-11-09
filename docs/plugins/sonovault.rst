Sonovault Plugin
================

The ``sonovault`` plugin adds `Sonovault <https://sonovault.now>`_ as a
metadata source for singleton imports. It is a DJ-oriented catalogue that
returns BPM, the musical key (also as Camelot code in ``camelot_key``), genre,
label and ISRC for a track found by artist and title. Album matching is not
supported by the service, so the plugin only contributes track candidates.

You need your own API key (free tier: 1.000 requests per month); the service's
terms require each user to use a personal key.

.. code-block:: yaml

    plugins: sonovault
    sonovault:
        apikey: svk_live_...
        search_limit: 5

The data source penalty defaults to ``0.2`` so that a perfect Sonovault match
still counts as a strong match in quiet mode.
