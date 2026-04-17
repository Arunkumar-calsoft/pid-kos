"""Clear all Neo4j nodes and relationships for a fresh pipeline run."""
import os, yaml
from neo4j import GraphDatabase

cfg = yaml.safe_load(open('config/neo4j.yaml'))['neo4j']
d = GraphDatabase.driver(cfg['uri'], auth=(cfg['user'], cfg['password']))
with d.session(database=cfg['database']) as s:
    c = s.run('MATCH (n) DETACH DELETE n').consume().counters
    print(f'Cleared: nodes={c.nodes_deleted}, rels={c.relationships_deleted}')
d.close()
print('DB clear complete.')
