"""Public crew surface: ``from zyko.crew import Crew``.

The sequential multi-agent layer (0.6.0): an ordered pipeline of configured
agents where each task template can reference the crew input (``{task}``),
the previous output (``{output}``) or any earlier step's ``{output_key}``.
Build agents with :mod:`zyko.agents` (YAML files or direct construction),
then::

    from zyko.crew import Crew

    crew = Crew(router=zk.router, tracer=zk.tracer)
    crew.add(classifier, "Classify: {task}", output_key="class")
    crew.add(replier, "Reply. Ticket: {task}\\nClass: {class}")
    result = crew.run("my invoice is late")
    print(result.output)              # final agent's answer
    print(result.outputs)             # every declared step output

or declaratively: ``zk.crew("crew.yaml").run("...")``.
"""

from zyko.crew.engine import Crew, CrewResult, CrewStep, fill_template
from zyko.crew.loader import load_crew

__all__ = [
    "Crew",
    "CrewStep",
    "CrewResult",
    "fill_template",
    "load_crew",
]
