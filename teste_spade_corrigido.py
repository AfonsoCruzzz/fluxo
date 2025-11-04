import asyncio
import spade
from spade.agent import Agent
from spade.behaviour import OneShotBehaviour
import logging

# Ativar logging detalhado
logging.basicConfig(level=logging.DEBUG)

class AgenteTeste(Agent):
    def __init__(self, jid, password):
        super().__init__(jid, password)
        # Configurações específicas para Prosody
        self.connection_timeout = 30
        
    class TesteComportamento(OneShotBehaviour):
        async def run(self):
            print("🎉 COMPORTAMENTO EXECUTADO - CONEXÃO BEM-SUCEDIDA!")
            print(f"Agente: {self.agent.jid}")
            await self.agent.stop()

    async def setup(self):
        print(f"⚙️ Configurando agente {self.jid}...")
        self.add_behaviour(self.TesteComportamento())

async def main():
    print("🚀 TESTE DE CONEXÃO COM PROSODY")
    print("=" * 50)
    
    # Lista de usuários para testar
    usuarios = [
        ("teste@localhost", "senha"),
        ("agente1@localhost", "senha"),
    ]
    
    for jid, password in usuarios:
        print(f"\n🔄 Testando {jid}...")
        
        agente = AgenteTeste(jid, password)
        
        try:
            # Tentar conexão sem auto_register primeiro
            await agente.start()
            print(f"✅ {jid} - Conexão bem-sucedida!")
            
            # Manter conectado por 3 segundos
            await asyncio.sleep(3)
            await agente.stop()
            
        except Exception as e:
            print(f"❌ {jid} - Erro na conexão: {e}")
            
            # Tentar registrar usuário
            try:
                import subprocess
                usuario = jid.split('@')[0]
                print(f"📝 Registrando usuário {usuario}...")
                
                resultado = subprocess.run([
                    "sudo", "prosodyctl", "register", 
                    usuario, "localhost", password
                ], capture_output=True, text=True, timeout=10)
                
                if resultado.returncode == 0:
                    print(f"✅ Usuário {usuario} registrado")
                    
                    # Tentar conexão novamente
                    await agente.start()
                    print(f"✅ {jid} - Conexão bem-sucedida após registro!")
                    await asyncio.sleep(3)
                    await agente.stop()
                else:
                    print(f"❌ Falha no registro: {resultado.stderr}")
                    
            except Exception as e2:
                print(f"❌ Falha completa: {e2}")
        
        print("-" * 50)

if __name__ == "__main__":
    spade.run(main())
