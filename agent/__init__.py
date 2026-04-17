# agent/__init__.py

class Phase8Agent:
    def __init__(self, neo4j, query_runner, trace_builder, llm):
        self.neo4j = neo4j
        self.query_runner = query_runner
        self.trace_builder = trace_builder
        self.llm = llm

    def answer(self, question: str) -> str:
        """
        End-to-end QA entry point for CLI
        """
        cypher = self.llm.to_cypher(question)
        records = self.query_runner.run(cypher)
        trace = self.trace_builder.build(records)
        return self.llm.final_answer(question, records, trace)
