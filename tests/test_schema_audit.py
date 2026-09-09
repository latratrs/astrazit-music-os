"""Adversarial regression tests using fictional fixtures only."""
import copy
import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import validate_schemas as audit


class SchemaAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas, cls.registry = audit.setup_validator()
        cls.work = audit.load_json(audit.EXAMPLES_DIR / 'work.single-recording.json')
        cls.recording = audit.load_json(audit.EXAMPLES_DIR / 'recording.single.json')
        cls.release = audit.load_json(audit.EXAMPLES_DIR / 'release.single.json')
        cls.ai = audit.load_json(audit.EXAMPLES_DIR / 'recording.ai-provisional.json')
        cls.hist_work = audit.load_json(audit.EXAMPLES_DIR / 'work.historical-import.json')
        cls.hist_rec = audit.load_json(audit.EXAMPLES_DIR / 'recording.historical-import.json')
        cls.context = audit.build_catalog_context([audit.load_json(p) for p in sorted(audit.EXAMPLES_DIR.glob('*.json'))])

    def errors(self, data, name=None, catalog_context=None):
        if name is None:
            if 'astrazit_work_id' in data and 'canonical_title' in data:
                name = 'work.schema.json'
            elif 'astrazit_recording_id' in data:
                name = 'recording.schema.json'
            elif 'astrazit_release_id' in data:
                name = 'release.schema.json'
        return audit.record_errors(data, name, self.schemas, self.registry, self.context if catalog_context is None else catalog_context)

    def test_id_namespaces(self):
        # Valid ID namespaces
        self.assertEqual([], self.errors(self.work, 'work.schema.json'))
        self.assertEqual([], self.errors(self.recording, 'recording.schema.json'))
        self.assertEqual([], self.errors(self.release, 'release.schema.json'))

        # Malformed AST-WRK ID
        d = copy.deepcopy(self.work)
        d['astrazit_work_id'] = 'AST-REC-000001'
        self.assertTrue(self.errors(d, 'work.schema.json'))
        d['astrazit_work_id'] = 'AST-WRK-999'
        self.assertTrue(self.errors(d, 'work.schema.json'))

        # Malformed AST-REC ID
        d = copy.deepcopy(self.recording)
        d['astrazit_recording_id'] = 'AST-WRK-000001'
        self.assertTrue(self.errors(d, 'recording.schema.json'))
        d['astrazit_recording_id'] = 'AST-REC-12'
        self.assertTrue(self.errors(d, 'recording.schema.json'))

        # Malformed AST-REL ID
        d = copy.deepcopy(self.release)
        d['astrazit_release_id'] = 'AST-ALB-000001'
        self.assertTrue(self.errors(d, 'release.schema.json'))
        d['astrazit_release_id'] = 'AST-REL-BAD'
        self.assertTrue(self.errors(d, 'release.schema.json'))

    def test_recording_referencing_work(self):
        d = copy.deepcopy(self.recording)
        self.assertEqual(d['astrazit_work_id'], 'AST-WRK-000001')
        d['astrazit_work_id'] = 'INVALID-REF'
        self.assertTrue(self.errors(d, 'recording.schema.json'))
        d.pop('astrazit_work_id')
        self.assertTrue(self.errors(d, 'recording.schema.json'))

    def test_release_tracklist_referencing_recordings(self):
        d = copy.deepcopy(self.release)
        self.assertEqual(d['tracklist'][0]['astrazit_recording_id'], 'AST-REC-000001')
        d['tracklist'][0]['astrazit_recording_id'] = 'AST-WRK-000001'
        self.assertTrue(self.errors(d, 'release.schema.json'))

    def test_approval_evidence(self):
        for field in ('approver', 'approved_at'):
            for value in ('MISSING', None, '', '   '):
                with self.subTest(field=field, value=value):
                    d = copy.deepcopy(self.ai)
                    p = d['provisional_enrichments']['suggested_tags']['provenance']
                    p.update(approval_status='APPROVED', approver='fictional-human', approved_at='2026-09-08T12:00:00Z')
                    if value == 'MISSING':
                        p.pop(field)
                    else:
                        p[field] = value
                    self.assertTrue(self.errors(d))

    def test_preserve_ai_origin_on_promotion(self):
        d = copy.deepcopy(self.ai)
        wrapper = d['provisional_enrichments'].pop('suggested_tags')
        p = wrapper['provenance']
        p.update(approval_status='APPROVED', approver='fictional-human', approved_at='2026-09-08T12:00:00Z', canonical_status='MASTER_METADATA')
        d['music']['moods'] = wrapper['value']
        d['metadata_provenance']['/music/moods'] = p
        self.assertEqual(p['source'], 'AI_GENERATED')
        self.assertEqual([], self.errors(d))
        p['approval_status'] = 'PENDING_APPROVAL'
        self.assertTrue(self.errors(d))

    def test_rights_approval_and_release_gate(self):
        # Work composition rights approval evidence
        for field in ('approved_by', 'approved_at'):
            d = copy.deepcopy(self.work)
            d['composition_rights'].pop(field)
            self.assertTrue(self.errors(d))
        
        # ACTIVE work is independent of release readiness; downstream releases still gate rights.
        d = copy.deepcopy(self.work)
        d['composition_rights']['approval_status'] = 'DRAFT'
        self.assertEqual([], self.errors(d))

        # Native recording in RELEASED requires approved work rights in cross-entity check
        ctx_unapproved = {'works': {'AST-WRK-000001': copy.deepcopy(d)}}
        rec = copy.deepcopy(self.recording)
        rec['lifecycle_status'] = 'RELEASED'
        self.assertTrue(any('requires APPROVED' in e for e in self.errors(rec, 'recording.schema.json', ctx_unapproved)))

    def test_historical_import_exception(self):
        # Historical import work may be ACTIVE with PENDING_HUMAN_APPROVAL rights
        self.assertEqual([], self.errors(self.hist_work, 'work.schema.json'))
        
        # Historical import recording may be RELEASED without failing
        self.assertEqual([], self.errors(self.hist_rec, 'recording.schema.json'))

        # Historical import does NOT imply rights approval: asserting APPROVED without approver must fail
        d = copy.deepcopy(self.hist_work)
        d['composition_rights']['approval_status'] = 'APPROVED'
        d['composition_rights']['approved_by'] = None
        self.assertTrue(self.errors(d, 'work.schema.json'))

    def test_work_recording_rights_separation(self):
        # Work owns writers and publishers, not master_owner
        d_work = copy.deepcopy(self.work)
        d_work['master_rights'] = {'master_owner': 'Invalid In Work'}
        self.assertTrue(self.errors(d_work, 'work.schema.json'))

        # Recording owns master_rights, not writers/publishers
        d_rec = copy.deepcopy(self.recording)
        d_rec['writers'] = [{'name': 'Invalid In Rec', 'percentage': 100.0, 'role': 'COMPOSER'}]
        self.assertTrue(self.errors(d_rec, 'recording.schema.json'))

    def test_exact_split_totals(self):
        for field in ('writers', 'publishers'):
            for shares, valid in [(['33.3', '33.3', '33.4'], True), (['99.9995'], False), (['40', '50'], False)]:
                d = copy.deepcopy(self.work)
                template = d['composition_rights'][field][0]
                d['composition_rights'][field] = [dict(template, name=f'Fictional {i}', percentage=Decimal(v)) for i, v in enumerate(shares)]
                self.assertEqual(not self.errors(d), valid)

    def test_formats_types_and_typos(self):
        for key, value in [('release_date', '2026-02-30'), ('astrazit_release_id', 123), ('titel', 'typo')]:
            d = copy.deepcopy(self.release)
            d[key] = value
            self.assertTrue(self.errors(d))
        d = copy.deepcopy(self.work)
        d['provenance']['generated_at'] = 'not-a-time'
        self.assertTrue(self.errors(d))
        d = copy.deepcopy(self.recording)
        d['assets'][0]['uri'] = 'not a uri'
        self.assertTrue(self.errors(d))

    def test_runtime_and_radio_contradictions(self):
        d = copy.deepcopy(self.recording)
        for key, value in [('play_count', 1), ('last_played_at', '2026-09-08T12:00:00Z'), ('eligibility_status', 'INELIGIBLE')]:
            d = copy.deepcopy(self.recording)
            d['radio'] = {'radio_eligible': True, 'eligibility_status': 'APPROVED'}
            d['radio'][key] = value
            self.assertTrue(self.errors(d, 'recording.schema.json'))
        for key in ('analytics', 'revenue'):
            d = copy.deepcopy(self.recording)
            d[key] = []
            self.assertTrue(self.errors(d, 'recording.schema.json'))

    def test_missing_ref_fails_without_network(self):
        schemas = copy.deepcopy(self.schemas)
        schemas['work.schema.json']['properties']['unused'] = {'$ref': 'missing.schema.json'}
        with patch('socket.socket', side_effect=AssertionError('Network forbidden')):
            with self.assertRaises(Exception) as caught:
                audit.check_references(schemas, self.registry)
            self.assertNotIsInstance(caught.exception, AssertionError)
            self.assertEqual([], self.errors(self.work))

    def test_release_ordering(self):
        d = copy.deepcopy(self.release)
        d['tracklist'] = [
            {'astrazit_recording_id': 'AST-REC-000001', 'track_number': 1},
            {'astrazit_recording_id': 'AST-REC-000002', 'track_number': 1}
        ]
        self.assertIn('tracklist: duplicate disc/track position', self.errors(d, 'release.schema.json'))
        d['tracklist'][1]['disc_number'] = 2
        self.assertEqual([], self.errors(d, 'release.schema.json'))

    def test_provider_neutral_pro_and_role_scope(self):
        d = copy.deepcopy(self.work)
        d['composition_rights']['registrations']['pro_registrations'][0]['organization'] = 'FICTIONAL_FOREIGN_PRO'
        self.assertEqual([], self.errors(d))
        d['composition_rights']['writers'][0]['role'] = 'PUBLISHER'
        self.assertTrue(self.errors(d))

    def test_currency_shape_only(self):
        d = audit.load_json(audit.TESTS_DIR / 'invalid-currency.json')
        self.assertTrue(self.errors(d, 'revenue-record.schema.json'))
        d['currency'] = 'ZZZ'
        self.assertEqual([], self.errors(d, 'revenue-record.schema.json'))

    def test_event_payload_versions(self):
        d = dict(event_id='fictional-event', event_type='WORK_CREATED', timestamp='2026-09-08T12:00:00Z', producer='fictional-test', entity_type='WORK', entity_id='AST-WRK-000001', data_version='2.0.0', data={'future_field': True})
        self.assertEqual([], self.errors(d, 'event-envelope.schema.json'))
        d['entity_id'] = 'AST-REC-000001'
        self.assertTrue(self.errors(d, 'event-envelope.schema.json'))

    def test_master_coownership_and_approval(self):
        d = copy.deepcopy(self.recording)
        d['master_rights']['owners'] = [{'name': 'Fictional A', 'percentage': Decimal('33.3')},
                                        {'name': 'Fictional B', 'percentage': Decimal('66.7')}]
        self.assertEqual([], self.errors(d))
        for value in (Decimal('66.6995'), Decimal('110'), Decimal('-1')):
            bad = copy.deepcopy(d)
            bad['master_rights']['owners'][1]['percentage'] = value
            self.assertTrue(any('percentage' in e or 'split total' in e for e in self.errors(bad)))
        for field in ('approved_by', 'approved_at'):
            bad = copy.deepcopy(d)
            bad['master_rights'].pop(field)
            self.assertTrue(any(field in e for e in self.errors(bad)))
        d['master_rights']['approval_status'] = 'PENDING_HUMAN_APPROVAL'
        self.assertTrue(any('APPROVED master rights' in e for e in self.errors(d)))

    def test_absent_or_invalid_context_fails_closed(self):
        for data, name in [(self.recording, 'recording.schema.json'), (self.release, 'release.schema.json')]:
            for context in (None, {}, {'works': {}, 'recordings': {}}):
                errors = audit.record_errors(data, name, self.schemas, self.registry, context)
                self.assertTrue(any('missing catalog context' in e for e in errors))
        ctx = copy.deepcopy(self.context)
        ctx['works'][self.work['astrazit_work_id']]['composition_rights'].pop('approved_at')
        self.assertTrue(any('approved_at' in e for e in self.errors(self.release, catalog_context=ctx)))
        ctx = copy.deepcopy(self.context)
        ctx['works'][self.work['astrazit_work_id']]['astrazit_work_id'] = 'AST-WRK-999999'
        self.assertTrue(any('context key' in e for e in self.errors(self.recording, catalog_context=ctx)))

    def test_native_release_checks_both_rights_domains(self):
        for state in ('RELEASE_READY', 'RELEASED'):
            d = copy.deepcopy(self.release)
            d['lifecycle_status'] = state
            for bucket, identifier, field in [('works', self.work['astrazit_work_id'], 'composition_rights'),
                                               ('recordings', self.recording['astrazit_recording_id'], 'master_rights')]:
                ctx = copy.deepcopy(self.context)
                ctx[bucket][identifier][field]['approval_status'] = 'PENDING_HUMAN_APPROVAL'
                self.assertTrue(any('requires APPROVED' in e for e in self.errors(d, catalog_context=ctx)))

    def test_historical_debt_and_new_release_not_bypassed(self):
        d = copy.deepcopy(self.hist_rec)
        self.assertEqual([], self.errors(d))
        d['historical_import']['rights_review_required'] = False
        self.assertTrue(any('review debt' in e for e in self.errors(d)))
        d = copy.deepcopy(self.hist_rec)
        d.pop('historical_import')
        self.assertTrue(any('historical_import' in e for e in self.errors(d)))
        d = copy.deepcopy(self.hist_rec)
        d['historical_import']['first_released_at'] = '2030-01-01T00:00:00Z'
        self.assertTrue(any('release evidence' in e for e in self.errors(d)))
        d = copy.deepcopy(self.hist_rec)
        d['lifecycle_status'] = 'RELEASE_READY'
        self.assertTrue(any('requires APPROVED' in e for e in self.errors(d)))
        d = copy.deepcopy(self.hist_rec)
        d['master_rights']['approval_status'] = 'APPROVED'
        self.assertTrue(any('approved_' in e for e in self.errors(d)))
        d = copy.deepcopy(self.release)
        d['tracklist'][0]['astrazit_recording_id'] = self.hist_rec['astrazit_recording_id']
        self.assertTrue(any('requires APPROVED' in e for e in self.errors(d)))
        # Existing released product can retain unresolved rights, but readiness cannot.
        d.update(catalog_origin='HISTORICAL_IMPORT', lifecycle_status='RELEASED', release_date='2024-05-01')
        d['historical_import'] = copy.deepcopy(self.hist_rec['historical_import'])
        self.assertEqual([], self.errors(d))
        d['lifecycle_status'] = 'RELEASE_READY'
        self.assertTrue(any('requires APPROVED' in e for e in self.errors(d)))

    def test_exact_identifier_and_pointer_syntax(self):
        for data, field in [(self.work, 'astrazit_work_id'), (self.recording, 'astrazit_recording_id'), (self.release, 'astrazit_release_id')]:
            d = copy.deepcopy(data)
            d[field] += '\n'
            self.assertTrue(self.errors(d))
        for pointer in ('xmusic', '/provisional_enrichments', '/provenance', '/music/moods/-1', '/music/moods/01', '/music/~2'):
            d = copy.deepcopy(self.ai)
            d['metadata_provenance'] = {pointer: copy.deepcopy(self.ai['metadata_provenance']['/music/moods'])}
            self.assertTrue(self.errors(d))

    def test_revenue_targets_and_event_namespaces(self):
        revenue = audit.load_json(audit.TESTS_DIR / 'invalid-currency.json')
        revenue['currency'] = 'ZZZ'
        for entity, prefix in [('WORK', 'WRK'), ('RECORDING', 'REC'), ('RELEASE', 'REL')]:
            revenue.update(entity_type=entity, entity_id=f'AST-{prefix}-000001')
            self.assertEqual([], self.errors(revenue, 'revenue-record.schema.json'))
            event = dict(event_id='fictional-event', event_type='RIGHTS_UPDATED', timestamp='2026-09-08T12:00:00Z', producer='fictional-test', entity_type=entity, entity_id=revenue['entity_id'], data_version='2.0.0', data={})
            self.assertEqual([], self.errors(event, 'event-envelope.schema.json'))
            revenue['entity_id'] = 'AST-000001'
            self.assertTrue(self.errors(revenue, 'revenue-record.schema.json'))
            event['entity_id'] = 'AST-000001'
            self.assertTrue(self.errors(event, 'event-envelope.schema.json'))

    def test_duplicate_context_identity(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate canonical ID'):
            audit.build_catalog_context([self.work, self.work])

    def test_negative_fixture_must_fail_for_expected_reason(self):
        data = copy.deepcopy(self.release)
        data['titel'] = 'Typo only'
        errors = list(audit.make_validator(self.schemas['release.schema.json'], self.registry).iter_errors(data))
        self.assertFalse(audit.expected_failure(errors, ('astrazit_release_id',), 'pattern'))
        data['astrazit_release_id'] = 'bad-id'
        errors = list(audit.make_validator(self.schemas['release.schema.json'], self.registry).iter_errors(data))
        self.assertFalse(audit.expected_failure(errors, ('astrazit_release_id',), 'pattern'))
        data.pop('titel')
        errors = list(audit.make_validator(self.schemas['release.schema.json'], self.registry).iter_errors(data))
        self.assertTrue(audit.expected_failure(errors, ('astrazit_release_id',), 'pattern'))

    def test_no_ast_allocator_exists(self):
        # OS-004 boundary test: confirm no ID allocator exists yet in codebase
        allocator_files = list(Path(audit.REPO_ROOT).rglob('*allocat*.py'))
        self.assertEqual([], allocator_files)

    def test_strict_json_reader(self):
        for text in ('{"x":NaN}', '{"x":1,"x":2}'):
            with self.assertRaises(ValueError):
                json.loads(text, parse_constant=audit.reject_constant, object_pairs_hook=audit.unique_object)


if __name__ == '__main__':
    unittest.main()
