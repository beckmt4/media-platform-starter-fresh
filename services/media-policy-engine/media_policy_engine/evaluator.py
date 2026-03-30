from __future__ import annotations

from .models import (
    AudioTrackFacts,
    AudioTrackType,
    MediaDomain,
    MediaFacts,
    PolicyAction,
    PolicyActionKind,
    PolicyEvaluationResult,
    StreamTarget,
    SubtitleTrackFacts,
    SubtitleTrackType,
)
from .policy_loader import (
    AudioDomainPolicy,
    LoadedPolicies,
    SubtitleDomainPolicy,
    TranscodeDomainPolicy,
)

# Map MediaDomain to the category key used in policy YAML files.
_DOMAIN_TO_CATEGORY: dict[MediaDomain, str] = {
    MediaDomain.domestic_live_action_movie: "domestic_live_action",
    MediaDomain.domestic_live_action_tv: "domestic_live_action",
    MediaDomain.international_live_action_movie: "international_live_action",
    MediaDomain.international_live_action_tv: "international_live_action",
    MediaDomain.domestic_animated_movie: "domestic_animation",
    MediaDomain.domestic_animated_tv: "domestic_animation",
    MediaDomain.international_animated_movie: "international_animation",
    MediaDomain.international_animated_tv: "international_animation",
    MediaDomain.anime_movie: "anime",
    MediaDomain.anime_series: "anime",
    MediaDomain.jav_adult: "adult",
}


class PolicyEvaluator:
    """Evaluates media facts against loaded policies and returns safe actions.

    All actions default to the least-destructive option. Ambiguous cases
    produce a send_to_review action rather than a remove_stream or mutation.
    """

    def __init__(self, policies: LoadedPolicies) -> None:
        self._policies = policies

    def evaluate(self, facts: MediaFacts) -> PolicyEvaluationResult:
        actions: list[PolicyAction] = []
        notes: list[str] = []

        # Blocked by catalog lock — skip all mutations
        if "locked" in facts.catalog_tags or "manual-source" in facts.catalog_tags:
            notes.append("item is locked by catalog tag — skipping mutation actions")
            actions.append(PolicyAction(
                kind=PolicyActionKind.skip_transcode,
                stream_target=StreamTarget.video,
                reason="catalog tag 'locked' or 'manual-source' blocks all mutations",
            ))
            return PolicyEvaluationResult(
                domain=facts.domain,
                file_path=facts.file_path,
                actions=actions,
                requires_review=False,
                evaluation_notes=notes,
            )

        category = _DOMAIN_TO_CATEGORY[facts.domain]

        actions += self._evaluate_subtitles(facts, category, notes)
        actions += self._evaluate_audio(facts, category, notes)
        actions += self._evaluate_transcode(facts, category, notes)

        return PolicyEvaluationResult(
            domain=facts.domain,
            file_path=facts.file_path,
            actions=actions,
            requires_review=any(a.requires_review for a in actions),
            evaluation_notes=notes,
        )

    # ------------------------------------------------------------------
    # Subtitle evaluation
    # ------------------------------------------------------------------

    def _evaluate_subtitles(
        self, facts: MediaFacts, category: str, notes: list[str]
    ) -> list[PolicyAction]:
        actions: list[PolicyAction] = []
        policy = self._policies.subtitle
        domain_policy = policy.domains.get(category, SubtitleDomainPolicy())
        universal = policy.universal

        has_english_subtitle = any(
            t.language == "en" for t in facts.subtitle_tracks
        )

        for track in facts.subtitle_tracks:
            actions += self._evaluate_subtitle_track(
                track, facts, universal, domain_policy, has_english_subtitle, notes
            )

        # adult: generate English if missing
        if (
            category == "adult"
            and domain_policy.generate_english_if_missing
            and not has_english_subtitle
        ):
            actions.append(PolicyAction(
                kind=PolicyActionKind.generate_english_subtitles,
                stream_target=StreamTarget.subtitle,
                reason="adult policy: generate_english_if_missing and no English subtitle found",
            ))
            notes.append("queued English subtitle generation")

        return actions

    def _evaluate_subtitle_track(
        self,
        track: SubtitleTrackFacts,
        facts: MediaFacts,
        universal,
        domain_policy: SubtitleDomainPolicy,
        has_english_subtitle: bool,
        notes: list[str],
    ) -> list[PolicyAction]:
        actions: list[PolicyAction] = []
        category = _DOMAIN_TO_CATEGORY[facts.domain]

        # Unknown language → quarantine
        if track.language == "unknown" and universal.quarantine_unknown_language:
            return [PolicyAction(
                kind=PolicyActionKind.quarantine_subtitle,
                stream_target=StreamTarget.subtitle,
                track_index=track.track_index,
                reason="universal policy: quarantine_unknown_language",
                requires_review=True,
            )]

        # Low-confidence detection → review
        review_threshold = domain_policy.require_review_below_confidence
        if review_threshold is not None and track.confidence < review_threshold:
            actions.append(PolicyAction(
                kind=PolicyActionKind.send_to_review,
                stream_target=StreamTarget.subtitle,
                track_index=track.track_index,
                reason=(
                    f"subtitle confidence {track.confidence:.2f}"
                    f" below threshold {review_threshold}"
                ),
                requires_review=True,
            ))

        # Forced tracks — always keep
        if track.track_type == SubtitleTrackType.forced and universal.keep_forced:
            actions.append(PolicyAction(
                kind=PolicyActionKind.keep_stream,
                stream_target=StreamTarget.subtitle,
                track_index=track.track_index,
                reason="universal policy: keep_forced",
            ))
            return actions

        # SDH English (domestic live action specific)
        if (
            track.track_type == SubtitleTrackType.sdh
            and track.language == "en"
            and domain_policy.keep_sdh_english
        ):
            actions.append(PolicyAction(
                kind=PolicyActionKind.keep_stream,
                stream_target=StreamTarget.subtitle,
                track_index=track.track_index,
                reason=f"{category} policy: keep_sdh_english",
            ))
            return actions

        # Signs/songs tracks (anime)
        if (
            track.track_type == SubtitleTrackType.signs_songs
            and domain_policy.keep_signs_songs_when_present
        ):
            actions.append(PolicyAction(
                kind=PolicyActionKind.keep_stream,
                stream_target=StreamTarget.subtitle,
                track_index=track.track_index,
                reason=f"{category} policy: keep_signs_songs_when_present",
            ))
            return actions

        # English subtitles
        if track.language == "en":
            keep = (
                universal.keep_english
                or domain_policy.keep_english
                or domain_policy.keep_full_english
            )
            if keep:
                actions.append(PolicyAction(
                    kind=PolicyActionKind.keep_stream,
                    stream_target=StreamTarget.subtitle,
                    track_index=track.track_index,
                    reason="policy: keep_english",
                ))
                return actions

        # Original language subtitles
        if track.language == facts.detected_original_language:
            keep = (
                universal.keep_original_language_subtitles_when_present
                or domain_policy.keep_original_language_subtitles_when_present
            )
            if keep:
                actions.append(PolicyAction(
                    kind=PolicyActionKind.keep_stream,
                    stream_target=StreamTarget.subtitle,
                    track_index=track.track_index,
                    reason="policy: keep_original_language_subtitles_when_present",
                ))
                return actions

        # Unknown disposition — flag for review rather than removing
        actions.append(PolicyAction(
            kind=PolicyActionKind.send_to_review,
            stream_target=StreamTarget.subtitle,
            track_index=track.track_index,
            reason=(
                f"subtitle track {track.track_index} language={track.language!r}"
                " does not match any keep rule"
            ),
            requires_review=True,
        ))
        return actions

    # ------------------------------------------------------------------
    # Audio evaluation
    # ------------------------------------------------------------------

    def _evaluate_audio(
        self, facts: MediaFacts, category: str, notes: list[str]
    ) -> list[PolicyAction]:
        actions: list[PolicyAction] = []
        policy = self._policies.audio
        domain_policy = policy.domains.get(category, AudioDomainPolicy())
        universal = policy.universal

        has_stereo = any(t.is_stereo for t in facts.audio_tracks)

        for track in facts.audio_tracks:
            actions += self._evaluate_audio_track(track, facts, universal, domain_policy, notes)

        if universal.create_stereo_fallback_when_missing and not has_stereo:
            actions.append(PolicyAction(
                kind=PolicyActionKind.create_stereo_fallback,
                stream_target=StreamTarget.audio,
                reason=(
                    "universal policy: create_stereo_fallback_when_missing"
                    " — no stereo track found"
                ),
            ))
            notes.append("queued stereo fallback creation")

        return actions

    def _evaluate_audio_track(
        self,
        track: AudioTrackFacts,
        facts: MediaFacts,
        universal,
        domain_policy: AudioDomainPolicy,
        notes: list[str],
    ) -> list[PolicyAction]:
        # Commentary → remove
        if track.track_type == AudioTrackType.commentary and universal.remove_commentary_by_default:
            return [PolicyAction(
                kind=PolicyActionKind.remove_stream,
                stream_target=StreamTarget.audio,
                track_index=track.track_index,
                reason="universal policy: remove_commentary_by_default",
            )]

        # Descriptive audio → review (not automatically removed)
        if track.track_type == AudioTrackType.descriptive:
            return [PolicyAction(
                kind=PolicyActionKind.send_to_review,
                stream_target=StreamTarget.audio,
                track_index=track.track_index,
                reason="descriptive audio track requires review before removal",
                requires_review=True,
            )]

        # Original language → keep
        if (
            track.language == facts.detected_original_language
            and universal.preserve_original_language
        ):
            return [PolicyAction(
                kind=PolicyActionKind.keep_stream,
                stream_target=StreamTarget.audio,
                track_index=track.track_index,
                reason="universal policy: preserve_original_language",
            )]

        # English → keep
        if track.language == "en" and universal.preserve_english_if_available:
            return [PolicyAction(
                kind=PolicyActionKind.keep_stream,
                stream_target=StreamTarget.audio,
                track_index=track.track_index,
                reason="universal policy: preserve_english_if_available",
            )]

        # Unmatched — flag for review
        return [PolicyAction(
            kind=PolicyActionKind.send_to_review,
            stream_target=StreamTarget.audio,
            track_index=track.track_index,
            reason=(
                f"audio track {track.track_index} language={track.language!r}"
                " does not match any keep rule"
            ),
            requires_review=True,
        )]

    # ------------------------------------------------------------------
    # Transcode evaluation
    # ------------------------------------------------------------------

    def _evaluate_transcode(
        self, facts: MediaFacts, category: str, notes: list[str]
    ) -> list[PolicyAction]:
        policy = self._policies.transcode
        domain_policy = policy.domains.get(category, TranscodeDomainPolicy())
        universal = policy.universal
        video = facts.video

        # Already target codec
        if video.codec.lower() == universal.target_video_codec and universal.skip_if_already_hevc:
            return [PolicyAction(
                kind=PolicyActionKind.skip_transcode,
                stream_target=StreamTarget.video,
                reason=f"universal policy: skip_if_already_hevc — codec is {video.codec}",
            )]

        # Remux protection
        if video.is_remux and universal.protect_remux:
            return [PolicyAction(
                kind=PolicyActionKind.skip_transcode,
                stream_target=StreamTarget.video,
                reason="universal policy: protect_remux — remux files are not transcoded",
            )]

        # Anime banding risk — always send to review before transcoding
        if domain_policy.manual_review_for_banding_risk:
            return [PolicyAction(
                kind=PolicyActionKind.send_to_review,
                stream_target=StreamTarget.video,
                reason=f"{category} policy: manual_review_for_banding_risk before transcode",
                requires_review=True,
            )]

        # Adult: skip low-value retranscodes (already handled above if hevc)
        if domain_policy.skip_low_value_retranscodes:
            notes.append("adult policy: skip_low_value_retranscodes — flagging for human review")
            return [PolicyAction(
                kind=PolicyActionKind.send_to_review,
                stream_target=StreamTarget.video,
                reason="adult policy: skip_low_value_retranscodes — human review before transcode",
                requires_review=True,
            )]

        # HDR protection (GPU budget unknown at evaluation time — flag for review)
        if video.is_hdr and universal.protect_high_bitrate_hdr_when_gpu_budget_is_poor:
            return [PolicyAction(
                kind=PolicyActionKind.send_to_review,
                stream_target=StreamTarget.video,
                reason=(
                    "universal policy: protect_high_bitrate_hdr_when_gpu_budget_is_poor"
                    " — HDR transcode needs human confirmation"
                ),
                requires_review=True,
            )]

        nvenc_note = (
            f" (allow_nvenc={domain_policy.allow_nvenc})" if domain_policy.allow_nvenc else ""
        )
        return [PolicyAction(
            kind=PolicyActionKind.flag_for_transcode,
            stream_target=StreamTarget.video,
            reason=(
                f"video codec {video.codec!r} is not {universal.target_video_codec!r}"
                f" — eligible for transcode{nvenc_note}"
            ),
        )]
