#!/usr/bin/env python3
import subprocess
import socket
import sys

def executar_comando(comando):
    try:
        resultado = subprocess.run(comando, shell=True, capture_output=True, text=True)
        return resultado.returncode == 0, resultado.stdout, resultado.stderr
    except Exception as e:
        return False, "", str(e)

def diagnostico_completo():
    print("🔍 DIAGNÓSTICO DO PROSODY")
    print("=" * 60)
    
    # 1. Status do serviço
    print("\n1. 📊 Status do serviço Prosody:")
    ok, saida, erro = executar_comando("sudo systemctl status prosody --no-pager")
    print(saida if ok else f"Erro: {erro}")
    
    # 2. Porta 5222
    print("\n2. 🔌 Porta 5222:")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        resultado = sock.connect_ex(('localhost', 5222))
        sock.close()
        if resultado == 0:
            print("✅ Porta 5222 está aceitando conexões")
        else:
            print(f"❌ Porta 5222 não está respondendo (código: {resultado})")
    except Exception as e:
        print(f"❌ Erro ao testar porta: {e}")
    
    # 3. Usuários registrados
    print("\n3. 👥 Usuários registrados:")
    ok, saida, erro = executar_comando("sudo prosodyctl listusers localhost")
    print(saida if ok else f"Erro: {erro}")
    
    # 4. Logs recentes
    print("\n4. 📝 Logs recentes do Prosody:")
    ok, saida, erro = executar_comando("sudo tail -20 /var/log/prosody/prosody.log")
    print(saida if ok else f"Logs não encontrados: {erro}")
    
    # 5. Configuração
    print("\n5. ⚙️ Verificação de configuração:")
    ok, saida, erro = executar_comando("sudo prosodyctl check")
    print(saida if ok else f"Erro na configuração: {erro}")
    
    print("\n" + "=" * 60)
    print("💡 Se todos os testes passarem, execute: python teste_spade_corrigido.py")

if __name__ == "__main__":
    diagnostico_completo()