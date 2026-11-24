-- SPDX-License-Identifier: EUPL-1.2
-- Notification topic of each pairing (spec EF-52, EF-60): random, unguessable, given in the pairing code.

ALTER TABLE pairing ADD COLUMN topic TEXT;
UPDATE pairing SET topic = lower(hex(randomblob(16))) WHERE topic IS NULL;
