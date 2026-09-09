#!/usr/bin/env python3
"""Offline Draft 2020-12 contract checks and deterministic catalog business rules."""
import json
import sys
from decimal import Decimal, localcontext
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / 'packages' / 'schemas'
EXAMPLES_DIR = SCHEMAS_DIR / 'examples'
TESTS_DIR = SCHEMAS_DIR / 'tests'
DIALECT = 'https://json-schema.org/draft/2020-12/schema'


def reject_constant(value):
    raise ValueError(f'Non-JSON numeric constant: {value}')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'), parse_float=Decimal,
                      parse_constant=reject_constant, object_pairs_hook=unique_object)


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def setup_validator(schema_dir=None):
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    schema_dir = Path(schema_dir or SCHEMAS_DIR)
    schemas, ids = {}, set()
    registry = Registry()  # No retrieval callback: unknown references fail offline.
    for path in sorted(schema_dir.glob('*.schema.json')):
        data = load_json(path)
        if data.get('$schema') != DIALECT:
            raise ValueError(f'{path.name}: wrong schema dialect')
        expected_id = 'https://schemas.astrazit.com/v1/' + path.name
        if data.get('$id') != expected_id or expected_id in ids:
            raise ValueError(f'{path.name}: invalid or duplicate schema ID')
        Draft202012Validator.check_schema(data)
        ids.add(expected_id)
        schemas[path.name] = data
        registry = registry.with_resource(expected_id, Resource.from_contents(data))
    if len(schemas) != 10:
        raise ValueError(f'Expected all ten schema contracts, found {len(schemas)}')
    check_references(schemas, registry)
    return schemas, registry


def check_references(schemas, registry):
    for name, schema in sorted(schemas.items()):
        resolver = registry.resolver(schema['$id'])
        for node in walk(schema):
            if '$ref' in node:
                resolver.lookup(node['$ref'])
            if node is not schema and '$id' in node:
                raise ValueError(f'{name}: nested IDs require scoped reference auditing')


def make_validator(schema, registry):
    from jsonschema import Draft202012Validator, FormatChecker
    checker = FormatChecker()
    for required in ('date', 'date-time', 'uri'):
        if required not in checker.checkers:
            raise RuntimeError(f'Missing {required} checker; install requirements-schema.txt')
    return Draft202012Validator(schema, registry=registry, format_checker=checker)


def split_errors(entries, label):
    shares = [Decimal(str(item['percentage'])) for item in entries]
    with localcontext() as ctx:
        ctx.prec = max(28, sum(len(x.as_tuple().digits) + abs(x.as_tuple().exponent)
                               for x in shares) + len(str(len(shares))) + 4)
        total = sum(shares, Decimal(0))
    return [] if total == Decimal(100) else [f'{label}: split total {total} != 100']


def build_catalog_context(records):
    context = {'works': {}, 'recordings': {}, 'releases': {}}
    for data in records:
        if 'astrazit_release_id' in data:
            bucket, key = 'releases', 'astrazit_release_id'
        elif 'astrazit_recording_id' in data:
            bucket, key = 'recordings', 'astrazit_recording_id'
        else:
            bucket, key = 'works', 'astrazit_work_id'
        identifier = data[key]
        if identifier in context[bucket]:
            raise ValueError(f'Duplicate canonical ID: {identifier}')
        context[bucket][identifier] = data
    return context


def related(data, bucket, identifier, schema_name, context, schemas, registry, errors):
    """Fail closed: absent or invalid referenced records cannot establish readiness."""
    record = (context or {}).get(bucket, {}).get(identifier)
    if record is None:
        errors.append(f'{bucket}: missing catalog context or referenced entity {identifier}')
        return None
    id_key = {'works': 'astrazit_work_id', 'recordings': 'astrazit_recording_id'}[bucket]
    if record.get(id_key) != identifier:
        errors.append(f'{bucket}: context key does not match record identity {identifier}')
        return None
    child_errors = record_errors(record, schema_name, schemas, registry, context)
    if child_errors:
        errors.extend(f'{identifier}: {error}' for error in child_errors)
        return None
    return record


def check_history(data, review_required, errors):
    if data.get('catalog_origin') != 'HISTORICAL_IMPORT':
        return
    from datetime import datetime
    history = data['historical_import']
    first = datetime.fromisoformat(history['first_released_at'].replace('Z', '+00:00').replace('z', '+00:00'))
    imported = datetime.fromisoformat(history['imported_at'].replace('Z', '+00:00').replace('z', '+00:00'))
    if first > imported:
        errors.append('historical_import: release evidence must precede or equal import time')
    if history['rights_review_required'] != review_required:
        errors.append('historical_import.rights_review_required does not match rights review debt')
    if 'release_date' in data and data['release_date'] != first.date().isoformat():
        errors.append('historical_import: release_date must match evidenced release date')


def requires_release_rights(data):
    status = data.get('lifecycle_status')
    return status in ('RELEASE_READY', 'RELEASED') and not (
        data.get('catalog_origin') == 'HISTORICAL_IMPORT' and status == 'RELEASED')


def business_errors(data, schema_name, catalog_context=None, schemas=None, registry=None):
    """Run after structural validation. Graph context is required for relationships."""
    errors = []
    if schema_name in ('work.schema.json', 'rights.schema.json'):
        rights = data['composition_rights'] if schema_name == 'work.schema.json' else data
        for group in ('writers', 'publishers'):
            errors.extend(split_errors(rights[group], group))
        if schema_name == 'work.schema.json':
            # ACTIVE describes a work, not a release authorization.
            check_history(data, rights['approval_status'] != 'APPROVED', errors)
            check_provenance_integrity(data, errors)
    elif schema_name == 'recording.schema.json':
        errors.extend(split_errors(data['master_rights']['owners'], 'master owners'))
        work = related(data, 'works', data['astrazit_work_id'], 'work.schema.json',
                       catalog_context, schemas, registry, errors)
        master_ok = data['master_rights']['approval_status'] == 'APPROVED'
        composition_ok = work is not None and work['composition_rights']['approval_status'] == 'APPROVED'
        if requires_release_rights(data):
            if not master_ok:
                errors.append('recording release readiness requires APPROVED master rights')
            if not composition_ok:
                errors.append('recording release readiness requires APPROVED composition rights')
        for name in ('intro_duration_seconds', 'outro_duration_seconds'):
            if data.get('radio', {}).get(name, 0) > data['music']['duration_seconds']:
                errors.append(f'radio.{name} exceeds track duration')
        check_history(data, not (master_ok and composition_ok), errors)
        check_provenance_integrity(data, errors)
    elif schema_name == 'release.schema.json':
        positions = [(t.get('disc_number', 1), t['track_number']) for t in data['tracklist']]
        if len(positions) != len(set(positions)):
            errors.append('tracklist: duplicate disc/track position')
        all_rights_approved = True
        for track in data['tracklist']:
            rec = related(data, 'recordings', track['astrazit_recording_id'], 'recording.schema.json',
                          catalog_context, schemas, registry, errors)
            if rec is None:
                all_rights_approved = False
                continue
            work = catalog_context['works'][rec['astrazit_work_id']]
            if (rec['master_rights']['approval_status'] != 'APPROVED' or
                    work['composition_rights']['approval_status'] != 'APPROVED'):
                all_rights_approved = False
        if requires_release_rights(data):
            if not all_rights_approved:
                errors.append('release readiness requires APPROVED composition and master rights for every recording')
            if data['provenance']['approval_status'] != 'APPROVED':
                errors.append('release readiness requires APPROVED release provenance')
        check_history(data, not all_rights_approved, errors)
    elif schema_name == 'revenue-record.schema.json':
        if data['period_end'] < data['period_start']:
            errors.append('period_end precedes period_start')
    return errors


def check_provenance_integrity(data, errors):
    """Pointers target canonical values, not staging/audit containers or Python indexes."""
    import re
    reserved = {'provisional_enrichments', 'metadata_provenance', 'provenance', 'historical_import'}
    for pointer, provenance in data.get('metadata_provenance', {}).items():
        if provenance['canonical_status'] != 'MASTER_METADATA':
            errors.append(f'{pointer}: canonical field provenance must be MASTER_METADATA')
        if not re.fullmatch(r'/(?:[^~]|~[01])*', pointer):
            errors.append(f'{pointer}: invalid JSON Pointer')
            continue
        tokens = [token.replace('~1', '/').replace('~0', '~') for token in pointer[1:].split('/')]
        if tokens[0] in reserved:
            errors.append(f'{pointer}: provenance must target a canonical value, not a staging/audit container')
            continue
        try:
            value = data
            for token in tokens:
                if isinstance(value, list):
                    if not re.fullmatch(r'0|[1-9][0-9]*', token):
                        raise ValueError('Invalid array index')
                    value = value[int(token)]
                elif isinstance(value, dict):
                    value = value[token]
                else:
                    raise TypeError('Cannot traverse a scalar')
        except (KeyError, IndexError, ValueError, TypeError):
            errors.append(f'{pointer}: provenance points to absent field')
    for key, wrapper in data.get('provisional_enrichments', {}).items():
        if wrapper['provenance']['canonical_status'] != 'PROVISIONAL':
            errors.append(f'{key}: staged enrichments must remain PROVISIONAL')


def record_errors(data, schema_name, schemas, registry, catalog_context=None):
    errors = sorted(make_validator(schemas[schema_name], registry).iter_errors(data),
                    key=lambda error: (error.json_path, error.message))
    if errors:
        return [f'{error.json_path}: {error.message}' for error in errors]
    return business_errors(data, schema_name, catalog_context, schemas, registry)


def expected_failure(errors, path, keyword, missing=None):
    """A negative fixture must fail at its intended field, not an unrelated defect."""
    def targeted(error):
        return tuple(error.absolute_path) == path and (
            missing is None or error.message == f"'{missing}' is a required property")
    return (bool(errors) and all(targeted(error) for error in errors)
            and any(error.validator == keyword for error in errors))


def main():
    try:
        for path in sorted(SCHEMAS_DIR.rglob('*.json')):
            load_json(path)
        schemas, registry = setup_validator()
        print(f'PASS: {len(schemas)} Draft 2020-12 meta-schemas and every reference checked offline')
        ok = True
        
        # Validate all examples
        examples = sorted(EXAMPLES_DIR.glob('*.json'))
        if len(examples) < 7:
            raise ValueError(f'Expected at least 7 positive examples, found {len(examples)}')
        
        # Build catalog context for cross-entity checks
        catalog_context = build_catalog_context([load_json(path) for path in examples])

        for path in examples:
            data = load_json(path)
            if 'astrazit_work_id' in data and 'canonical_title' in data:
                sname = 'work.schema.json'
            elif 'astrazit_recording_id' in data:
                sname = 'recording.schema.json'
            elif 'astrazit_release_id' in data:
                sname = 'release.schema.json'
            else:
                raise ValueError(f'Unknown example entity type in {path.name}')

            errors = record_errors(data, sname, schemas, registry, catalog_context)
            print(('FAIL' if errors else 'PASS') + ': ' + path.name)
            for error in errors:
                print('  ' + error)
            ok = ok and not errors

        # Validate negative tests
        expected = {
            'invalid-missing-id.json': ('recording.schema.json', (), 'required', 'astrazit_recording_id'),
            'invalid-malformed-id.json': ('recording.schema.json', ('astrazit_recording_id',), 'pattern', None),
            'invalid-malformed-work-id.json': ('work.schema.json', ('astrazit_work_id',), 'pattern', None),
            'invalid-malformed-release-id.json': ('release.schema.json', ('astrazit_release_id',), 'pattern', None),
            'invalid-percentage.json': ('work.schema.json', ('composition_rights', 'writers', 0, 'percentage'), 'maximum', None),
            'invalid-currency.json': ('revenue-record.schema.json', ('currency',), 'pattern', None),
            'invalid-enum.json': ('recording.schema.json', ('lifecycle_status',), 'enum', None),
        }
        for filename, (schema_name, path, keyword, missing) in expected.items():
            errors = list(make_validator(schemas[schema_name], registry).iter_errors(load_json(TESTS_DIR / filename)))
            matched = expected_failure(errors, path, keyword, missing)
            print(('PASS' if matched else 'FAIL') + ': expected rejection ' + filename)
            ok = ok and matched

        # Run unit tests
        import unittest
        suite = unittest.defaultTestLoader.discover(str(REPO_ROOT / 'tests'), pattern='test_schema_audit.py')
        if suite.countTestCases() == 0:
            raise ValueError('Missing adversarial regression tests')
        result = unittest.TextTestRunner(stream=sys.stdout, verbosity=1).run(suite)
        ok = ok and result.wasSuccessful()
        print('PASS: all checks' if ok else 'FAIL: contract validation')
        return 0 if ok else 1
    except ImportError as error:
        print(f'FAIL: dependency missing ({error}); run python -m pip install -r requirements-schema.txt')
        return 1
    except Exception as error:
        print(f'FAIL: {type(error).__name__}: {error}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
