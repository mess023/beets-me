Singles Plugin
==============

The ``singles`` plugin turns beets into a batch pipeline for loose
(non-album) tracks and ships its own web interface, started with
``beet singles-web [host] [port]`` (default ``0.0.0.0 8338``):

- ``/``: inbox and library status, batch size, start/stop, live progress,
  the last added tracks with cover, key and BPM, skipped files with a retry
  button, and an event list plus the raw log. Each batch runs
  ``beet import -s -q`` on the next files from the inbox.
- ``/plugins``: enable or disable plugins and store their settings
  (API keys and the like) in ``config.yaml``.

The interface is dark by default and follows the system's light preference
or the toggle in the header. It does not use the :doc:`web </plugins/web>`
plugin.

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
