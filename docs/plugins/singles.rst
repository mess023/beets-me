Singles Plugin
==============

The ``singles`` plugin turns beets into a batch pipeline for loose
(non-album) tracks and adds two pages to the :doc:`web </plugins/web>`
interface:

- ``/singles/``: pick a batch size, start or stop a run and follow the log.
  Each batch runs ``beet import -s -q`` on the next files from the inbox.
- ``/singles/plugins``: enable or disable plugins and store their settings
  (API keys and the like) in ``config.yaml``.

On top of that the plugin:

- remembers the creation time of the original file as ``creation_date`` and
  exposes ``$month_folder`` (for example ``July 2025``) for path formats,
- detects the musical key (``initial_key`` plus ``camelot_key``) with
  Essentia when installed, otherwise with librosa,
- fetches and embeds cover art for singletons through the
  :doc:`fetchart </plugins/fetchart>` plugin, which on its own only handles
  albums.

Configuration
-------------

.. code-block:: yaml

    singles:
        inbox: /music/inbox
        batch_size: 20
        auto_key: yes
        auto_art: yes
    paths:
        singleton: $month_folder/$artist - $title%sunique{}

``creation_date`` uses the file's birth time where the kernel and filesystem
expose it (Linux statx, Windows, macOS) and falls back to the modification time
otherwise, which is common on network shares.
