import { Anchor, Code, List, Stack, Table, Text, Title } from "@mantine/core";

// In-app onboarding for first-time users (PR-V1-28). Static content
// mirrors the README; updating one requires updating the other (see
// brief §"Riesgos conocidos").
const SPEC_URL =
  "https://github.com/takeo7/niwa/blob/main/docs/SPEC.md";
const ROADMAP_URL =
  "https://github.com/takeo7/niwa/blob/main/docs/plans/FOUND-20260422-onboarding.md";

export function HelpPage() {
  return (
    <Stack gap="xl">
      <Title order={2}>Help</Title>

      <Stack gap="xs">
        <Title order={3}>What Niwa does</Title>
        <Text>
          Niwa is a local autonomous code agent. You describe a task in
          natural language; Niwa creates a branch in your repo, runs
          Claude Code to do the work, verifies the result, commits, and
          (optionally) opens a PR via the GitHub CLI.
        </Text>
        <Text>
          <strong>It runs entirely on your machine.</strong> Your code
          never leaves the laptop. Niwa needs you to clone the repos
          yourself — it doesn't connect to GitHub to import them.
        </Text>
      </Stack>

      <Stack gap="xs">
        <Title order={3}>Quickstart</Title>

        <Text fw={600}>1. Clone a repo to your machine</Text>
        <Code block>
{`git clone https://github.com/you/your-repo
cd your-repo
git status   # working tree must be clean`}
        </Code>

        <Text fw={600}>2. Create a project</Text>
        <Code block>
{`In the projects list, click "New project" and fill:
  • slug: short id, e.g. "playground"
  • name: human-readable label
  • kind: library / web-deployable / script
  • local_path: absolute path of your clone
  • git_remote: optional, GitHub URL for auto PRs
  • autonomy_mode: safe (default) or dangerous`}
        </Code>

        <Text fw={600}>3. Create your first task</Text>
        <Code block>
{`Inside the project, click "New task" and describe the work
in natural language, e.g.:

  "Add a section to the README explaining how to run tests."

Watch the run stream live. When it ends with status \`done\`,
check your repo for the new branch.`}
        </Code>
      </Stack>

      <Stack gap="xs">
        <Title order={3}>Project kinds</Title>
        <Table withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>kind</Table.Th>
              <Table.Th>behaviour</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            <Table.Tr>
              <Table.Td>
                <Code>library</Code>
              </Table.Td>
              <Table.Td>
                Niwa runs the project's tests after writing code.
              </Table.Td>
            </Table.Tr>
            <Table.Tr>
              <Table.Td>
                <Code>web-deployable</Code>
              </Table.Td>
              <Table.Td>
                Like <Code>library</Code> + serves built output at{" "}
                <Code>/api/deploy/&lt;slug&gt;/</Code>.
              </Table.Td>
            </Table.Tr>
            <Table.Tr>
              <Table.Td>
                <Code>script</Code>
              </Table.Td>
              <Table.Td>
                Skips the test step (for one-shot helpers).
              </Table.Td>
            </Table.Tr>
          </Table.Tbody>
        </Table>
      </Stack>

      <Stack gap="xs">
        <Title order={3}>Task states</Title>
        <List>
          <List.Item>
            <Code>inbox</Code>: created but not queued for execution.
          </List.Item>
          <List.Item>
            <Code>queued</Code>: waiting for the executor to pick it up.
          </List.Item>
          <List.Item>
            <Code>running</Code>: executor is actively working.
          </List.Item>
          <List.Item>
            <Code>waiting_input</Code>: Claude asked you something. Reply
            in the task detail page to resume.
          </List.Item>
          <List.Item>
            <Code>done</Code>: completed and verified.
          </List.Item>
          <List.Item>
            <Code>failed</Code>: didn't pass verification (artifacts
            missing, tests failed, etc.).
          </List.Item>
          <List.Item>
            <Code>cancelled</Code>: stopped manually.
          </List.Item>
        </List>
      </Stack>

      <Stack gap="xs">
        <Title order={3}>Autonomy modes</Title>
        <List>
          <List.Item>
            <Code>safe</Code> (default): Niwa opens a PR; you merge.
          </List.Item>
          <List.Item>
            <Code>dangerous</Code>: Niwa auto-merges via{" "}
            <Code>gh pr merge --squash</Code> after verify passes. A red
            banner is shown on the project detail page while this mode
            is active.
          </List.Item>
        </List>
      </Stack>

      <Stack gap="xs">
        <Title order={3}>Common gotchas</Title>
        <List>
          <List.Item>
            "Working tree clean" required before creating a task.
          </List.Item>
          <List.Item>
            The branch is created from the repo's default branch (
            <Code>main</Code>/<Code>master</Code>), not from your
            current checkout.
          </List.Item>
          <List.Item>
            <Code>gh</Code> CLI not installed → no auto-open of PRs
            (status will say <Code>gh_missing</Code>); other steps still
            work.
          </List.Item>
        </List>
      </Stack>

      <Stack gap="xs">
        <Title order={3}>Architecture and spec</Title>
        <List>
          <List.Item>
            Full spec:{" "}
            <Anchor href={SPEC_URL} target="_blank" rel="noreferrer">
              docs/SPEC.md
            </Anchor>
          </List.Item>
          <List.Item>
            Roadmap v1.1:{" "}
            <Anchor href={ROADMAP_URL} target="_blank" rel="noreferrer">
              docs/plans/FOUND-20260422-onboarding.md
            </Anchor>
          </List.Item>
        </List>
      </Stack>
    </Stack>
  );
}
