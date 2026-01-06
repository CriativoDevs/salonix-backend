
from django.core.management.base import BaseCommand
from django.db import connection, transaction

class Command(BaseCommand):
    help = 'Fix staging migration state by dropping notifications tables'

    def handle(self, *args, **options):
        tables_to_drop = [
            'notifications_notificationlog',
            'notifications_notificationdevice',
            'notifications_notification',
        ]
        
        with connection.cursor() as cursor:
            # Desativa verificação de chave estrangeira temporariamente para permitir drop em qualquer ordem
            cursor.execute('SET FOREIGN_KEY_CHECKS = 0;')
            
            for table in tables_to_drop:
                self.stdout.write(f'Checking table {table}...')
                try:
                    cursor.execute(f"DROP TABLE IF EXISTS {table}")
                    self.stdout.write(self.style.SUCCESS(f'Dropped table {table}'))
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f'Error dropping {table}: {e}'))

            # Limpa o histórico de migrações do app notifications para garantir clean slate
            self.stdout.write('Cleaning django_migrations history for notifications app...')
            cursor.execute("DELETE FROM django_migrations WHERE app = 'notifications'")
            
            cursor.execute('SET FOREIGN_KEY_CHECKS = 1;')

        self.stdout.write(self.style.SUCCESS('Successfully cleaned up notifications tables. Now run: python manage.py migrate notifications'))
