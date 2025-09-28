import os, random, string

for i in range(1, 101):
    name = "User" + ''.join(random.choices(string.ascii_letters, k=5))
    email = name.lower() + "@example.com"
    actief = random.choice(["true", "false"])
    cmd = f"python sql.py insert customers --user daan --values \"id={i}, name='{name}', email='{email}', actief={actief}\""
    os.system(cmd)

