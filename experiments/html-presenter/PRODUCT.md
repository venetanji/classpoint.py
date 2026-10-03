# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

The user identifies ait4x/deckgen as the slide renderer, paired with classpoint.py.
Keep deckgen's Reveal.js output and activity specifications. The POC adds a local
Python bridge and a small HTML/JavaScript presenter shell, not another slide renderer.

## Users and Purpose

An instructor presents directly in HTML while students join and answer in the
existing ClassPoint student app. The acceptance case is one class started from
HTML, a real slide snapshot visible to students, and a multiple-choice activity open.

## Constraints

No PowerPoint runtime. No credentials in published HTML. Starting a live class must
be an explicit instructor action. Preserve the deckgen/ait4x slide design and source
specifications. The POC supports multiple choice; other activity types are out of scope.

## Evidence

The local decrypted capture confirms class startup, slide-image upload and
navigation, multiple-choice startup, answer delivery, submission closure, and class
shutdown. It does not establish a supported third-party login/authorization contract.
