# Archetecture

## User Interfaces

- A very simple web interface, where I can input 
    - a link 
        - and expect a download of the audio from the link.
    - links (list or google docs sheet) 
        - and expect a download a lossless-compression bundle of all audio from the links given as input.

- A very simple CLI tool, where I can input 
    - a link 
        - and expect a download of the audio from the link.
    - links (list or google docs sheet) 
        - and expect a download a lossless-compression bundle of all audio from the links given as input.

## API User Cases

- Given a _link_, I expect to receive an audio file back of a tolerable format.
- Given _Links_ (in the form of a list, google drive spreadsheet, CSV, ...), I expect to receive audio files back of a tolerable format.

## Tolerable Formats

- WAV, 
- MP3 (320kbps or higher, warning if less)
- FLAC
- _More to be added_

## Tolerable Sources

- Youtube
- Soundcloud
- Spotify
- _More to be added_