---
name: uteki-business-graph-stage
metadata:
  version: graph-stage-v1-experiment
  status: experimental-unvalidated
---
# Build the business object and relationship graph

This capability is the OBJECT/RELATION GRAPH stage of business analysis. It uses the existing business-draft-v2 contract. The host will later render this same graph with the approved Uteki Mermaid profile. Do not produce presentation markup.

Read the entire selected source. Build a graph from the company through reportable segments, the material named business groupings, businesses, and the named product/platform objects that the source explains. The graph must let a reader follow what the company does, how its material groups relate, and where its described platforms belong. This is not an independent-segment accounting register. A named platform needs no separate revenue, legal entity or proof of independent business status to be a node.

For this stage, products_services, customers and monetization must be empty lists on EVERY node. Do not hide graph objects in descriptions or product lists. Instead give each materially defined named product/platform/group its own node. Generic capability enumerations (compute/network/storage etc.) need not be individual nodes. Detailed capabilities, customer attributes and monetization are deferred, not absent from the source. This explicit stage scope supersedes general suggestions to include all those attributes in one response.

Each node has its original official name, a supported kind (company/reportable_segment/business/offering_group), an optional supported role, and ONE short factual definition. Use business with application_platform where the source defines a platform; otherwise role may be null. Preserve distinctions between a business whole, a named group and a service subset. Bind name and description separately to exact excerpts and ensure evidence_block_ids contains both sets. Node description is an identity/definition, not a place to hide unmodeled children, unsupported scope or relations.

Each edge asserts something about its ENTIRE source and target. If only a service subset is explicitly listed in a group, create a separate named subset node, link THAT subset to the stated group, and to its whole where supported by the source. Do not connect a mixed whole using cloud-only or other subset evidence. Do not assume that a broader target fixes this range mismatch. Use multiple parents when the source supports both an identity/subset link and a reporting/grouping link; this is a graph, not necessarily a strict tree.

Use child->parent for part_of/reported_under; provider->beneficiary for supports. Reported_under identifies reporting placement, not legal ownership. For part_of, keep the scope aligned to the source. Use explicit for a directly stated inclusion, derived for a reasoned context/definition/brand relationship. The word 'belongs' need not literally appear, but names alone or proximity alone are not sufficient. A derived edge must cite the actual passages and explain how their definitions plus context support that precise relation. Avoid manufacturing support edges unrelated to the requested business structure.

Before returning, check every material named platform or group described in the text: is its identity represented and is its relation explained? Read all paragraphs, including issuer offerings inside Competition. A material object cannot disappear merely because it lacks separate revenue or a formal organization chart. Unsupported links remain concrete unknown business questions. Questions about whether to create a node, how to use a schema or whether to include competitors are implementation choices, not business unknowns. Distinguish material not read from a point not stated in the selected section.

Do not output competitor entities as issuer businesses. Do not assume whole-report coverage. Do not use prior candidates, remembered company facts or evaluation expectations. Do not impose a fixed node count. Keep summary about selected source coverage. Every block gets an honest disposition; deferred customer/financial attributes may be context, not a claim of extraction completeness. The expected output is a navigable evidence-grounded graph, not a full attribute dataset.
