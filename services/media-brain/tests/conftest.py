from __future__ import annotations

import pytest

# Minimal mediainfo JSON for a typical MKV with one video, two audio, one subtitle track.
SAMPLE_MEDIAINFO_JSON = {
    "media": {
        "track": [
            {
                "@type": "General",
                "Format": "Matroska",
                "Duration": "5400.000",
            },
            {
                "@type": "Video",
                "Format": "HEVC",
                "Width": "1920",
                "Height": "1080",
                "HDR_Format": None,
                "transfer_characteristics": "",
                "Language": None,
            },
            {
                "@type": "Audio",
                "Format": "AAC",
                "Language": "jpn",
                "Channels": "2",
                "Default": "Yes",
            },
            {
                "@type": "Audio",
                "Format": "AC-3",
                "Language": "eng",
                "Channels": "6",
                "Default": "No",
            },
            {
                "@type": "Text",
                "Format": "UTF-8",
                "Language": "eng",
                "Title": "English",
                "Forced": "No",
                "Default": "Yes",
            },
        ]
    }
}

SAMPLE_MEDIAINFO_HDR = {
    "media": {
        "track": [
            {"@type": "General", "Format": "Matroska", "Duration": "7200.0"},
            {
                "@type": "Video",
                "Format": "HEVC",
                "Width": "3840",
                "Height": "2160",
                "HDR_Format": "SMPTE ST 2086",
                "transfer_characteristics": "PQ",
            },
            {
                "@type": "Audio",
                "Format": "TrueHD",
                "Language": "jpn",
                "Channels": "8",
                "Default": "Yes",
            },
        ]
    }
}
