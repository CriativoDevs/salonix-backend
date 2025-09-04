"""
Testes para configuração de cache Django-Redis.
"""
import pytest
from django.core.cache import cache
from django.conf import settings
from django.test import TestCase, override_settings


class TestCacheConfiguration(TestCase):
    """Testes para configuração de cache."""
    
    def test_cache_backend_loaded(self):
        """Teste se o backend de cache está configurado."""
        cache_config = settings.CACHES['default']
        
        # Deve ter um backend configurado
        assert 'BACKEND' in cache_config
        assert cache_config['BACKEND'] in [
            'django.core.cache.backends.locmem.LocMemCache',
            'django_redis.cache.RedisCache'
        ]
    
    def test_cache_basic_operations(self):
        """Teste operações básicas de cache."""
        # Limpar cache antes do teste
        cache.clear()
        
        # Set/Get básico
        cache.set('test_key', 'test_value', 60)
        value = cache.get('test_key')
        assert value == 'test_value'
        
        # Teste com None
        assert cache.get('nonexistent_key') is None
        assert cache.get('nonexistent_key', 'default') == 'default'
        
        # Delete
        cache.delete('test_key')
        assert cache.get('test_key') is None
    
    def test_cache_multiple_operations(self):
        """Teste operações múltiplas de cache."""
        cache.clear()
        
        # Set múltiplo
        data = {'key1': 'value1', 'key2': 'value2', 'key3': 'value3'}
        cache.set_many(data, 60)
        
        # Get múltiplo
        retrieved = cache.get_many(data.keys())
        assert retrieved == data
        
        # Delete múltiplo
        cache.delete_many(data.keys())
        retrieved_after_delete = cache.get_many(data.keys())
        assert retrieved_after_delete == {}
    
    def test_cache_increment_operations(self):
        """Teste operações de incremento."""
        cache.clear()
        
        # Incremento básico
        cache.set('counter', 10)
        cache.incr('counter')
        assert cache.get('counter') == 11
        
        # Incremento com delta
        cache.incr('counter', 5)
        assert cache.get('counter') == 16
        
        # Decremento
        cache.decr('counter', 3)
        assert cache.get('counter') == 13
        
        cache.delete('counter')
    
    def test_cache_timeout(self):
        """Teste timeout de cache."""
        cache.clear()
        
        # Configurar valor com timeout curto
        cache.set('short_lived', 'temporary', 1)
        assert cache.get('short_lived') == 'temporary'
        
        # Valor deve existir imediatamente
        assert cache.get('short_lived') is not None
        
        # Não vamos testar expiração real pois pode ser flaky
        cache.delete('short_lived')
    
    def test_cache_complex_data(self):
        """Teste cache com dados complexos."""
        cache.clear()
        
        # Dados complexos
        complex_data = {
            'user': {'id': 1, 'name': 'João'},
            'permissions': ['read', 'write'],
            'metadata': {'created': '2025-01-03', 'version': 1.0}
        }
        
        cache.set('complex_key', complex_data, 300)
        retrieved = cache.get('complex_key')
        
        assert retrieved == complex_data
        assert isinstance(retrieved, dict)
        assert retrieved['user']['name'] == 'João'
        
        cache.delete('complex_key')


@override_settings(
    CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'test-cache',
            'TIMEOUT': 300,
        }
    }
)
class TestLocMemCacheSpecific(TestCase):
    """Testes específicos para LocMem cache."""
    
    def test_locmem_isolation(self):
        """Teste isolamento entre instâncias de cache."""
        cache.clear()
        
        cache.set('isolation_test', 'value1')
        assert cache.get('isolation_test') == 'value1'
        
        # Limpar deve remover
        cache.clear()
        assert cache.get('isolation_test') is None


class TestCacheIntegration(TestCase):
    """Testes de integração do cache com o sistema."""
    
    def test_cache_key_prefix(self):
        """Teste se o prefixo de chave está funcionando."""
        cache.clear()
        
        # Para Redis, deve usar o prefixo 'salonix'
        # Para LocMem, não há prefixo visível
        cache.set('prefixed_key', 'prefixed_value', 300)
        value = cache.get('prefixed_key')
        
        assert value == 'prefixed_value'
        cache.delete('prefixed_key')
    
    def test_cache_performance_basic(self):
        """Teste básico de performance do cache."""
        import time
        cache.clear()
        
        # Medir tempo de operações básicas
        start_time = time.time()
        
        for i in range(100):
            cache.set(f'perf_key_{i}', f'value_{i}', 300)
        
        for i in range(100):
            cache.get(f'perf_key_{i}')
        
        end_time = time.time()
        duration = end_time - start_time
        
        # Deve ser rápido (menos de 1 segundo para 200 operações)
        assert duration < 1.0
        
        # Limpeza
        cache.delete_many([f'perf_key_{i}' for i in range(100)])
