import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from registration.phone_audit import AUDIT_SPECS, apply_phone_fixes, build_phone_fix_report


class Command(BaseCommand):
    help = "Preview or apply safe Bangladesh phone normalizations without touching country values."

    def add_arguments(self, parser):
        parser.add_argument(
            '--model',
            action='append',
            dest='models',
            help='Limit the fix pass to one or more model keys.',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=50,
            help='Maximum number of candidate rows to print in text mode.',
        )
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Write the phone updates to the database.',
        )
        parser.add_argument(
            '--as-json',
            action='store_true',
            help='Print the preview or apply result as JSON.',
        )

    def handle(self, *args, **options):
        valid_model_keys = {spec.key for spec in AUDIT_SPECS}
        selected_models = options.get('models') or []
        invalid = sorted(set(selected_models) - valid_model_keys)
        if invalid:
            raise CommandError(
                'Unknown model key(s): {}. Valid choices: {}'.format(
                    ', '.join(invalid),
                    ', '.join(sorted(valid_model_keys)),
                )
            )

        if options['apply']:
            with transaction.atomic():
                result = apply_phone_fixes(selected_models=selected_models)
        else:
            result = build_phone_fix_report(selected_models=selected_models)

        if options['as_json']:
            self.stdout.write(json.dumps(result, indent=2, sort_keys=True))
            return

        summary = result['summary']
        heading = 'Phone Fix Apply Summary' if options['apply'] else 'Phone Fix Preview'
        self.stdout.write(self.style.MIGRATE_HEADING(heading))
        self.stdout.write(f"Safe phone-fix candidates: {summary['candidate_count']}")
        self.stdout.write(f"Skipped because of duplicates: {summary['skipped_due_to_duplicate']}")
        if options['apply']:
            self.stdout.write(f"Rows updated: {summary['updated_count']}")

        rows = (result.get('updated') or result.get('candidates') or [])[: max(options['limit'], 0)]
        if rows:
            self.stdout.write('')
            self.stdout.write(self.style.MIGRATE_HEADING('Sample Rows'))
            for row in rows:
                issue_text = ', '.join(row['issues']) if row['issues'] else 'none'
                self.stdout.write(
                    f"[{row['model_label']} #{row['id']}] scope={row['scope']} issues={issue_text}"
                )
                self.stdout.write(
                    f"  name={row['name'] or '-'} email={row['email'] or '-'} country={row['country'] or '-'} old_phone={row['raw_phone']} new_phone={row['normalized_phone']}"
                )
