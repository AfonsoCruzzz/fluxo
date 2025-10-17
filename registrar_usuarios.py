#!/usr/bin/env python3
import subprocess

def registrar_usuario(usuario, senha="senha"):
    """Registrar usuário no Prosody"""
    try:
        resultado = subprocess.run([
            "sudo", "prosodyctl", "register",
            usuario, "localhost", senha
        ], capture_output=True, text=True, check=True)
        
        print(f"✅ Usuário {usuario}@localhost registrado")
        return True
        
    except subprocess.CalledProcessError as e:
        if "exists" in e.stderr.lower():
            print(f"⚠️  Usuário {usuario} já existe")
            return True
        else:
            print(f"❌ Erro ao registrar {usuario}: {e.stderr}")
            return False

# Registrar usuários comuns para desenvolvimento
usuarios = ["agente1", "agente2", "teste", "admin"]

for usuario in usuarios:
    registrar_usuario(usuario)