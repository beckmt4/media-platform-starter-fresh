---
name: media-policy
description: Apply media-domain policy rules for subtitles, audio, transcode, sourcing, and arr lock behavior.
---

# Media Policy Skill

Use this skill whenever editing files under `config/policies/`, `config/media-domains.yaml`, or workflow logic that changes media decisions.

## Required reasoning path

1. Identify the media domain:
   - domestic_live_action_movie
   - domestic_live_action_tv
   - international_live_action_movie
   - international_live_action_tv
   - domestic_animated_movie
   - domestic_animated_tv
   - international_animated_movie
   - international_animated_tv
   - anime_movie
   - anime_series
   - jav_adult
2. Identify which rules are universal and which are domain-specific.
3. Confirm what is preserved, what is removed, and what is quarantined.
4. Confirm review-gate requirements.
5. Update tests and examples.

## Never do this

- Never collapse anime and JAV into generic international rules.
- Never delete unknown subtitle tracks without quarantine policy.
- Never drop original/native audio.
