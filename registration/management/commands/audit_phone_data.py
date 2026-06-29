import json

from django.core.management.base import BaseCommand, CommandError

from registration.phone_audit import AUDIT_SPECS, run_phone_audit


class Command(BaseCommand):
    help = "Audit phone and country data for SMS readiness without changing records."

    def add_arguments(self, parser):
        parser.add_argument(
            '--model',
            action='append',
            dest='models',
            help='Limit the audit to one or more model keys.',
        )
        parser.add_argument(
            '--include-valid',
            action='store_true',
            help='Include rows that have no issues in the detailed output.',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=50,
            help='Maximum number of detailed rows to print in text mode.',
        )
        parser.add_argument(
            '--as-json',
            action='store_true',
            help='Print the full report as JSON.',
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

        report = run_phone_audit(
            selected_models=selected_models,
            include_valid=options['include_valid'],
        )

        if options['as_json']:
            self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
            return

        summary = report['summary']
        self.stdout.write(self.style.MIGRATE_HEADING('Phone Data Audit Summary'))
        self.stdout.write(f"Total records scanned: {summary['total_records']}")
        self.stdout.write(f"Detailed rows returned: {summary['returned_records']}")
        self.stdout.write(f"Duplicate normalized-phone groups: {summary['duplicate_group_count']}")

        self.stdout.write('')
        self.stdout.write('Status counts:')
        for key, value in sorted(summary['status_counts'].items()):
            self.stdout.write(f'  - {key}: {value}')

        self.stdout.write('')
        self.stdout.write('Issue counts:')
        if summary['issue_counts']:
            for key, value in sorted(summary['issue_counts'].items()):
                self.stdout.write(f'  - {key}: {value}')
        else:
            self.stdout.write('  - none')

        self.stdout.write('')
        self.stdout.write('Model counts:')
        for key, value in sorted(summary['model_counts'].items()):
            self.stdout.write(f'  - {key}: {value}')

        rows = report['rows'][: max(options['limit'], 0)]
        if rows:
            self.stdout.write('')
            self.stdout.write(self.style.MIGRATE_HEADING('Sample Detailed Rows'))
            for row in rows:
                issue_text = ', '.join(row['issues']) if row['issues'] else 'none'
                phone_text = row['normalized_phone'] or '-'
                country_text = row['normalized_country'] or row['raw_country'] or '-'
                self.stdout.write(
                    f"[{row['model_label']} #{row['id']}] scope={row['scope']} status={row['status']} issues={issue_text}"
                )
                self.stdout.write(
                    f"  name={row['name'] or '-'} email={row['email'] or '-'} country={country_text} raw_phone={row['raw_phone'] or '-'} normalized_phone={phone_text}"
                )
                if row['phone_error']:
                    self.stdout.write(f"  phone_error={row['phone_error']}")

        duplicate_groups = report['duplicate_groups'][: max(options['limit'], 0)]
        if duplicate_groups:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING('Duplicate Normalized Phone Groups'))
            for group in duplicate_groups:
                self.stdout.write(
                    f"  - model={group['model_key']} scope={group['scope']} normalized_phone={group['normalized_phone']} record_ids={group['record_ids']}"
                )
