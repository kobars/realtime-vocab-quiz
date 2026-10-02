<!-- AI-ASSISTED: a card with every part, and the interactive card at rest and hovered. -->
<script setup lang="ts">
import { Badge, Button, Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '../../src'
import SpecimenItem from '../SpecimenItem.vue'
</script>

<template>
  <SpecimenItem label="Card with every part">
    <Card class="w-full">
      <CardHeader>
        <CardTitle>Everyday verbs</CardTitle>
        <CardDescription>10 questions · 20 s each</CardDescription>
        <CardAction>
          <Badge variant="mint">
            Open
          </Badge>
        </CardAction>
      </CardHeader>
      <CardContent>Pick the word that matches the definition.</CardContent>
      <CardFooter>
        <Button size="sm">
          Join
        </Button>
      </CardFooter>
    </Card>
  </SpecimenItem>
  <div class="grid gap-6 sm:grid-cols-2">
    <SpecimenItem label="interactive, rest">
      <Card
        interactive
        class="w-full"
      >
        <CardTitle>Lift</CardTitle>
      </Card>
    </SpecimenItem>
    <SpecimenItem label="interactive, hover">
      <Card
        interactive
        data-preview="hover"
        class="w-full"
      >
        <CardTitle>Lift</CardTitle>
      </Card>
    </SpecimenItem>
  </div>
</template>
