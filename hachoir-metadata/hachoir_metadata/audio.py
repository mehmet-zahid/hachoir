from hachoir_metadata.metadata import Metadata, MultipleMetadata, registerExtractor
from hachoir_parser.audio import AuFile, MpegAudioFile, RealAudioFile, AiffFile
from hachoir_parser.container import OggFile, RealMediaFile
from hachoir_core.i18n import _
from hachoir_core.error import warning
from hachoir_core.tools import makePrintable

class OggMetadata(MultipleMetadata):
    key_to_attr = {
        "ARTIST": "artist",
        "ALBUM": "album",
        "TRACKNUMBER": "track_number",
        "TITLE": "title",
        "DATE": "creation_date",
        "ORGANIZATION": "organization",
        "GENRE": "music_genre",
        "": "comment",
        "COMPOSER": "music_composer",
        "DESCRIPTION": "comment",
        "COMMENT": "comment",
        "WWW": "url",
        "LICENSE": "copyright",
    }

    def extract(self, ogg):
        for index, page in enumerate(ogg.array("page")):
            if "vorbis_hdr" in page:
                meta = Metadata()
                self.vorbisHeader(page["vorbis_hdr"], meta)
                self.addGroup("audio[]", meta, "Audio")
            if "theora_hdr" in page:
                meta = Metadata()
                self.theoraHeader(page["theora_hdr"], meta)
                self.addGroup("video[]", meta, "Video")
            if "comment" in page:
                self.vorbisComment(page["comment"])
            if 3 <= index:
                # Only process pages 0..3
                break

    def theoraHeader(self, header, meta):
        meta.compression = "Theora"
        meta.format_version = "Theora version %u.%u (revision %u)" % (\
            header["version_major"].value,
            header["version_minor"].value,
            header["version_revision"].value)
        meta.width = header["frame_width"].value
        meta.height = header["frame_height"].value
        if header["fps_den"].value:
            meta.frame_rate = float(header["fps_num"].value) / header["fps_den"].value
        if header["aspect_ratio_den"].value:
            meta.aspect_ratio = float(header["aspect_ratio_num"].value) / header["aspect_ratio_den"].value
        meta.pixel_format = header["pixel_format"].display
        meta.comment = "Quality: %s" % header["quality"].value

    def vorbisHeader(self, header, meta):
        meta.compression = "Vorbis"
        meta.sample_rate = header["audio_sample_rate"].value
        meta.nb_channel = header["audio_channels"].value
        meta.format_version = "Vorbis version %s" % header["vorbis_version"].value
        meta.bit_rate = header["bitrate_nominal"].value

    def vorbisComment(self, comment):
        self.producer = comment["vendor"].value
        for metadata in comment.array("metadata"):
            if "=" in metadata.value:
                key, value = metadata.value.split("=", 1)
                key = key.upper()
                if key in self.key_to_attr:
                    setattr(self, self.key_to_attr[key], value)
                elif value:
                    warning("Skip Ogg comment %s: %s" % (key, value))

class AuMetadata(Metadata):
    def extract(self, audio):
        self.sample_rate = audio["sample_rate"].value
        self.nb_channel = audio["channels"].value
        self.compression = audio["codec"].display
        if "info" in audio:
            self.comment = audio["info"].value
        self.bits_per_sample = audio.getBitsPerSample()
        if hasattr(self, "bits_per_sample"):
            self.bit_rate = self.bits_per_sample[0] * audio["channels"].value * audio["sample_rate"].value
        if "audio_data" in audio \
        and hasattr(self, "bit_rate"):
            self.duration = audio["audio_data"].size * 1000 / self.bit_rate[0]

class RealAudioMetadata(Metadata):
    def extract(self, real):
        if "metadata" in real:
            info = real["metadata"]
            self.title = info["title"].value
            self.author = info["author"].value
            self.copyright = info["copyright"].value
            self.comment = info["comment"].value
        if real["version"].value == 4:
            self.sample_rate = real["sample_rate"].value
            self.nb_channel = real["channels"].value
            self.compression = real["FourCC"].value
        self.format_version = "Real audio version %s" % real["version"].value

class RealMediaMetadata(MultipleMetadata):
    key_to_attr = {
        "generated by": "producer",
        "creation date": "creation_date",
        "modification date": "last_modification",
        "description": "comment",
    }
    def extract(self, media):
        if "file_prop" in media:
            prop = media["file_prop"]
            self.bit_rate = prop["avg_bit_rate"].value
            self.duration = prop["duration"].value
        if "content_desc" in media:
            content = media["content_desc"]
            self.title = content["title"].value
            self.author = content["author"].value
            self.copyright = content["copyright"].value
            self.comment = content["comment"].value
        for stream in media.array("stream_prop"):
            meta = Metadata()
            if stream["stream_start"].value:
                meta.comment = "Start: %s" % stream["stream_start"].value
            if stream["mime_type"].value == "logical-fileinfo":
                for prop in stream.array("file_info/prop"):
                    key = prop["name"].value.lower()
                    value = prop["value"].value
                    if key in self.key_to_attr:
                        setattr(self, self.key_to_attr[key], value)
                    elif value:
                        warning("Skip %s: %s" % (prop["name"].value, value))
            else:
                meta.bit_rate = stream["avg_bit_rate"].value
                meta.duration = stream["duration"].value
                meta.mime_type = stream["mime_type"].value
            meta.title = stream["desc"].value
            index = 1 + stream["stream_number"].value
            self.addGroup("stream[%u]" % index, meta, "Stream #%u" % index)

class MpegAudioMetadata(Metadata):
    tag_to_key = {
        # ID3 version 2.2
        "TP1": "author",
        "COM": "comment",
        "TEN": "producer",
        "TRK": "track_number",
        "TAL": "album",
        "TT2": "title",
        "TYE": "creation_date",

        # ID3 version 2.3+
        "TPE1": "author",
        "COMM": "comment",
        "TENC": "producer",
        "TRCK": "track_number",
        "TALB": "album",
        "TIT2": "title",
        "TYER": "creation_date",
        "WXXX": "url"
    }

    def processID3v2(self, field):
        # Read value
        if "content" not in field:
            return
        content = field["content"]
        if "text" not in content:
            return
        if "title" in content and content["title"].value:
            value = "%s: %s" % (content["title"].value, content["text"].value)
        else:
            value = content["text"].value

        # Known tag?
        tag = field["tag"].value
        if tag not in self.tag_to_key:
            if tag:
                if isinstance(tag, str):
                    tag = makePrintable(tag, "ISO-8859-1", to_unicode=True)
                warning("Skip ID3v2 tag %s: %s" % (tag, value))
            return
        setattr(self, self.tag_to_key[tag], value)

    def readID3v2(self, id3):
        for field in id3:
            if field.is_field_set and "tag" in field:
                self.processID3v2(field)

    def extract(self, mp3):
        if "/frames/frame[0]" in mp3:
            frame = mp3["/frames/frame[0]"]
            self.nb_channel = frame["channel_mode"].display
            self.format_version = "MPEG version %s layer %s" % \
                (frame["version"].display, frame["layer"].display)
            sample_rate = frame.getSampleRate() # may returns None on error
            if sample_rate:
                self.sample_rate = sample_rate
            self.bits_per_sample = 16
            bit_rate = frame.getBitRate() # may returns None on error
            if bit_rate:
                if mp3["frames"].looksConstantBitRate():
                    self.bit_rate = bit_rate
                    # Guess music duration using fixed bit rate
                    self.duration = (mp3["frames"].size * 1000) / bit_rate
                else:
                    self.bit_rate = _("Variable bit rate (VBR)")
        if "id3v1" in mp3:
            id3 = mp3["id3v1"]
            self.comment = id3["comment"].value
            self.author = id3["author"].value
            self.title = id3["song"].value
            self.album = id3["album"].value
            if id3["year"].value != "0":
                self.creation_date = id3["year"].value
            if "track_nb" in id3:
                self.track_number = id3["track_nb"].value
        if "id3v2" in mp3:
            self.readID3v2(mp3["id3v2"])

class AiffMetadata(Metadata):
    def extract(self, aiff):
        if "common" in aiff:
            info = aiff["common"]
            rate = int(info["sample_rate"].value)
            if rate:
                self.sample_rate = rate
                self.duration = info["nb_sample"].value * 1000 // rate
            self.nb_channel = info["nb_channel"].value
            self.bits_per_sample = info["sample_size"].value
            if "codec" in info:
                self.compression = info["codec"].display

registerExtractor(AuFile, AuMetadata)
registerExtractor(MpegAudioFile, MpegAudioMetadata)
registerExtractor(OggFile, OggMetadata)
registerExtractor(RealMediaFile, RealMediaMetadata)
registerExtractor(RealAudioFile, RealAudioMetadata)
registerExtractor(AiffFile, AiffMetadata)

