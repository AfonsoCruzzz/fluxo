import asyncio
import spade
from spade.agent import Agent
from spade.behaviour import OneShotBehaviour

class AgenteTeste(Agent):
    class TesteComportamento(OneShotBehaviour):
        async def run(self):
            print("🎉 Conectado ao Prosody com sucesso!")
            print(f"🤖 Agente: {self.agent.jid}")
            await self.agent.stop()

    async def setup(self):
        print("⚙️ Configurando agente...")
        self.add_behaviour(self.TesteComportamento())

async def main():
    print("🚀 Testando conexão com Prosody...")
    
    # Criar agente - NÃO usar auto_register com Prosody
    agente = AgenteTeste("teste@localhost", "senha")
    
    try:
        # Primeiro tentar sem auto_register
        await agente.start()
        print("✅ Conexão bem-sucedida!")
        await asyncio.sleep(2)
        
    except Exception as e:
        print(f"⚠️  Primeira tentativa falhou: {e}")
        print("🔄 Tentando registrar usuário...")
        
        # Registrar usuário manualmente primeiro
        import subprocess
        try:
            subprocess.run([
                "sudo", "prosodyctl", "register", 
                "teste", "localhost", "senha"
            ], check=True)
            print("✅ Usuário registrado!")
            
            # Tentar novamente
            await agente.start()
            print("✅ Conexão bem-sucedida após registro!")
            await asyncio.sleep(2)
            
        except Exception as e2:
            print(f"❌ Falha completa: {e2}")
    
    finally:
        await agente.stop()

if __name__ == "__main__":
    spade.run(main())
