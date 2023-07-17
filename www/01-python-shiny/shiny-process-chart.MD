``` mermaid

flowchart TD

    user["<strong>User</strong>
    (of software)"]
    subgraph Application
    server["<strong>Server</strong>
    - Executes python code.
    - Processes data.
    - Translates outputs into HTML.
    "]
    ui["<strong>User Interface</strong>
    - Displays input widgets.
    - Displays rendered server outputs.
    - Can be adjusted with HTML & CSS."]
    db[("Data")]
    end
    user -->|Input Values| ui <-->|Dynamic Values| server
    db -->|read| server
    

```
