import asyncio
import spade

async def teste_conexao_basica():
    """Teste mais simples possível"""
    from spade.agent import Agent
    
    class AgenteMinimo(Agent):
        async def setup(self):
            print("✅ CONECTADO! Setup executado com sucesso!")
            await self.stop()
    
    print("🧪 Teste mínimo de conexão...")
    agente = AgenteMinimo("teste@localhost", "senha")
    
    try:
        await agente.start()
        print("🎉 SUCESSO TOTAL!")
        return True
    except Exception as e:
        print(f"❌ FALHA: {e}")
        return False

if __name__ == "__main__":
    resultado = spade.run(teste_conexao_basica)
    exit(0 if resultado else 1)
