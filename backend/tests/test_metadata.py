"""Offline unit tests for clazzziks.metadata (no network/yt-dlp calls)."""

# pylint: disable=missing-function-docstring

import pytest

from clazzziks.metadata import build_metadata


def test_youtube_music_structured_metadata_passthrough():
    info = {"title": "ignored", "track": "Track Title", "artist": "Real Artist"}
    meta = build_metadata(info, fallback_title="ignored")
    assert meta.title == "Track Title"
    assert meta.artist == "Real Artist"
    assert not any("artist" in w.lower() and "determine" in w.lower() for w in meta.warnings)


def test_artist_track_order_confirmed_by_uploader():
    info = {"title": "Artist Name - Track Title", "uploader": "Artist Name - Topic"}
    meta = build_metadata(info, fallback_title="x")
    assert meta.artist == "Artist Name"
    assert meta.title == "Track Title"
    assert not any("assumed" in w.lower() for w in meta.warnings)


def test_track_artist_reversed_order_caught_by_uploader():
    info = {"title": "Track Title - Artist Name", "uploader": "Artist Name"}
    meta = build_metadata(info, fallback_title="x")
    assert meta.artist == "Artist Name"
    assert meta.title == "Track Title"


def test_no_uploader_match_assumes_artist_first_and_warns():
    info = {"title": "Some Artist - Some Track"}
    meta = build_metadata(info, fallback_title="x")
    assert meta.artist == "Some Artist"
    assert meta.title == "Some Track"
    assert any("assumed" in w.lower() for w in meta.warnings)


def test_remix_override_uses_remixer_as_artist():
    info = {"title": "Original Artist - Track (DJ Remixer Remix)"}
    meta = build_metadata(info, fallback_title="x")
    assert meta.artist == "DJ Remixer"
    assert meta.title == "Track (DJ Remixer Remix)"


def test_featured_artist_is_stripped_from_artist_field():
    info = {"title": "Artist feat. Someone - Track", "uploader": "Artist"}
    meta = build_metadata(info, fallback_title="x")
    assert meta.artist == "Artist"
    assert "Someone" not in meta.artist


def test_track_field_duplicating_title_is_not_trusted():
    # yt-dlp's generic/SoundCloud extractors often set info["track"] as a
    # plain alias for info["title"], not real structured metadata (and the
    # accompanying "artist" field can be an unrelated multi-name blob) — the
    # split heuristic must still run in that case.
    info = {
        "title": "Baseli, Ale Montoya - Space Glitch",
        "track": "Baseli, Ale Montoya - Space Glitch",
        "artist": "Baseli， Ale Montoya， Space Kraft",
        "uploader": "Baseli",
    }
    meta = build_metadata(info, fallback_title="x")
    assert meta.title == "Space Glitch"
    assert meta.artist == "Baseli, Ale Montoya"


def test_track_field_genuinely_distinct_from_title_is_trusted():
    info = {"title": "Artist - Track (Official Video)", "track": "Track", "artist": "Artist"}
    meta = build_metadata(info, fallback_title="x")
    assert meta.title == "Track"
    assert meta.artist == "Artist"


def test_no_hyphen_falls_back_and_warns():
    info = {"title": "Just A Track Name"}
    meta = build_metadata(info, fallback_title="x")
    assert meta.artist is None
    assert meta.title == "Just A Track Name"
    assert any("could not determine an artist" in w.lower() for w in meta.warnings)


def test_thumbnail_picks_largest():
    info = {
        "title": "A - B",
        "thumbnails": [
            {"url": "small.jpg", "width": 120, "height": 90},
            {"url": "large.jpg", "width": 1280, "height": 720},
            {"url": "medium.jpg", "width": 640, "height": 480},
        ],
    }
    meta = build_metadata(info, fallback_title="x")
    assert meta.thumbnail_url == "large.jpg"


def test_thumbnail_falls_back_to_single_field():
    info = {"title": "A - B", "thumbnail": "only.jpg"}
    meta = build_metadata(info, fallback_title="x")
    assert meta.thumbnail_url == "only.jpg"


def test_missing_genre_and_album_warn_with_expected_wording():
    info = {"title": "A - B"}
    meta = build_metadata(info, fallback_title="x")
    assert meta.genre is None
    assert meta.album is None
    assert "No genre information available from source." in meta.warnings
    assert "No album info available; using thumbnail as artwork fallback." in meta.warnings


def test_no_artwork_available_warns():
    info = {"title": "A - B"}
    meta = build_metadata(info, fallback_title="x")
    assert meta.thumbnail_url is None
    assert "No artwork available for this track." in meta.warnings


def test_genre_from_categories_fallback():
    info = {"title": "A - B", "categories": ["Music"]}
    meta = build_metadata(info, fallback_title="x")
    assert meta.genre == "Music"


def test_album_present_no_warning():
    info = {"title": "A - B", "album": "Some Album"}
    meta = build_metadata(info, fallback_title="x")
    assert meta.album == "Some Album"
    assert not any("album" in w.lower() for w in meta.warnings)


@pytest.mark.parametrize(
    "title,expected_artist,expected_title",
    [
        ("T-Pain - Up Down", "T-Pain", "Up Down"),
        ("Anti-Hero - Taylor Swift Cover", "Anti-Hero", "Taylor Swift Cover"),
        ("X-Ray Spex - Oh Bondage Up Yours", "X-Ray Spex", "Oh Bondage Up Yours"),
    ],
)
def test_split_ignores_unspaced_hyphen_inside_a_name(title, expected_artist, expected_title):
    # A hyphen with no surrounding whitespace ("T-Pain", "X-Ray") is part of a
    # name, not the artist/title separator — the real (properly spaced)
    # separator later in the string must be the one that's used.
    meta = build_metadata({"title": title}, fallback_title="x")
    assert meta.artist == expected_artist
    assert meta.title == expected_title


def test_split_does_not_fire_on_a_name_with_only_an_unspaced_hyphen():
    # No properly-spaced separator anywhere -> no split at all.
    meta = build_metadata({"title": "X-Ray Spex"}, fallback_title="x")
    assert meta.artist is None
    assert meta.title == "X-Ray Spex"


@pytest.mark.parametrize(
    "title",
    ["Left Boy - Some Track", "Craft Spells - Another Track", "Swift Justice - Track"],
)
def test_feat_stripping_does_not_truncate_names_containing_ft_substring(title):
    meta = build_metadata({"title": title}, fallback_title="x")
    assert meta.artist == title.split(" - ")[0]


@pytest.mark.parametrize(
    "qualifier", ["Radio Edit", "Album Edit", "Clean Edit", "Extended Edit"]
)
def test_remix_override_ignores_generic_edit_qualifiers(qualifier):
    info = {"title": f"Original Artist - Track ({qualifier})"}
    meta = build_metadata(info, fallback_title="x")
    assert meta.artist == "Original Artist"


def test_remix_override_still_fires_for_a_real_remixer():
    info = {"title": "Original Artist - Track (DJ Whoever Remix)"}
    meta = build_metadata(info, fallback_title="x")
    assert meta.artist == "DJ Whoever"


def test_short_title_does_not_spuriously_confirm_against_uploader():
    # "A" is trivially a substring of almost any uploader name; that
    # coincidence shouldn't count as a confirmed artist/track split.
    info = {"title": "A - Some Longer Track Name", "uploader": "Various Artists Official"}
    meta = build_metadata(info, fallback_title="x")
    assert any("assumed" in w.lower() for w in meta.warnings)


def test_album_duplicating_title_is_not_trusted():
    info = {"title": "Some Track", "album": "Some Track"}
    meta = build_metadata(info, fallback_title="x")
    assert meta.album is None
    assert "No album info available; using thumbnail as artwork fallback." in meta.warnings
